import { randomUUID } from 'node:crypto'
import { Client } from 'pg'
import jwt from 'jsonwebtoken'

const DEV_JWT_SECRET = 'dev-secret-key-change-in-prod' // mesma secret do docker-compose.yml (dev only)
const DB_URL =
  process.env.E2E_DATABASE_URL ??
  'postgresql://orgcred:orgcred_dev_password@localhost:5433/orgcred_dev'

export interface CenarioAtivacao {
  usuarioId: string
  accessToken: string
  operacaoAtivavelId: string
  operacaoBloqueadaId: string
}

/**
 * Sem projeto Supabase real neste repositório (ver DECISOES_PENDENTES.md),
 * o E2E não pode autenticar contra um IdP de verdade. Em vez de pular o
 * fluxo de login, mintamos um JWT válido com a MESMA secret de
 * desenvolvimento que o backend já usa (docker-compose.yml,
 * ORGCRED_SUPABASE_JWT_SECRET) — o backend não sabe (nem precisa saber)
 * que o token não veio do Supabase de verdade; a interceptação de rede
 * mockando apenas a resposta do POST de login do Supabase é o único
 * "fake" desta suíte, tudo o mais (banco, API, regras de negócio) é real.
 */
export async function semearCenarioAtivacao(): Promise<CenarioAtivacao> {
  const client = new Client({ connectionString: DB_URL })
  await client.connect()

  try {
    // Dev DB, não produção — reset das tabelas do cenário para tornar o
    // teste repetível entre execuções locais.
    await client.query(
      // movimento_bancario entra explicitamente: ele e referenciado POR
      // parcela, entao o cascade de operacao_credito nao o alcanca — sem
      // isto o documento unico de uma execucao anterior sobrevive e a
      // proxima falha com "ja existe um movimento".
      'truncate capital_ledger, operacao_credito, esc_capital_social, movimento_bancario cascade',
    )
    await client.query("delete from tomador where cnpj like '9999%'")
    await client.query("delete from usuario where email = 'e2e-operador@orgcred.test'")

    const usuarioId = randomUUID()
    await client.query(
      `insert into usuario (id, email, nome, papel, ativo) values ($1, $2, $3, $4, $5)`,
      [usuarioId, 'e2e-operador@orgcred.test', 'Operador E2E', 'operador', true],
    )

    const tomadorResult = await client.query<{ id: string }>(
      `insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
       values ($1, 'Padaria E2E ME', 'ME', 'Formoso', 'GO', true) returning id`,
      [`9999${String(Date.now()).slice(-10)}`],
    )
    const tomadorId = tomadorResult.rows[0].id

    // Capital social de 50.000 — uma operação de 30.000 cabe; uma segunda
    // de 30.000 excede o disponível (20.000), provando o bloqueio OC001.
    await client.query(
      `insert into esc_capital_social (valor, tipo_evento) values (50000, 'constituicao')`,
    )

    const opAtivavel = await client.query<{ id: string }>(
      `insert into operacao_credito
        (tomador_id, tipo, valor_principal, taxa_juros_mensal, sistema_amortizacao,
         numero_parcelas, status, registro_entidade_ref)
       values ($1, 'emprestimo', 30000, 2.5, 'PRICE', 12, 'registrada', 'REG-E2E-1')
       returning id`,
      [tomadorId],
    )

    const opBloqueada = await client.query<{ id: string }>(
      `insert into operacao_credito
        (tomador_id, tipo, valor_principal, taxa_juros_mensal, sistema_amortizacao,
         numero_parcelas, status, registro_entidade_ref)
       values ($1, 'financiamento', 30000, 3.0, 'SAC', 24, 'registrada', 'REG-E2E-2')
       returning id`,
      [tomadorId],
    )

    const accessToken = jwt.sign(
      {
        sub: usuarioId,
        email: 'e2e-operador@orgcred.test',
        role: 'authenticated',
        aud: 'authenticated',
      },
      DEV_JWT_SECRET,
      { algorithm: 'HS256', expiresIn: '1h' },
    )

    return {
      usuarioId,
      accessToken,
      operacaoAtivavelId: opAtivavel.rows[0].id,
      operacaoBloqueadaId: opBloqueada.rows[0].id,
    }
  } finally {
    await client.end()
  }
}

export interface CenarioAging {
  usuarioId: string
  accessToken: string
  /** Ativa, com a primeira parcela vencida há mais de 90 dias. */
  operacaoAtrasadaId: string
}

/**
 * Cenário da régua de inadimplência.
 *
 * O usuário aqui é ADMIN, não operador: `POST /cobranca/aging/processar`
 * exige admin, e semear um operador faria o teste falhar por 403 sem que
 * isso dissesse nada sobre a régua.
 *
 * Envelhecer a parcela exige desabilitar `trg_parcela_imutavel` — o
 * vencimento é imutável desde a migration 007. Ter que desligar o trigger
 * para montar o cenário é justamente a prova de que, pela aplicação, não
 * existe caminho para reescrever a agenda.
 */
export async function semearCenarioAging(): Promise<CenarioAging> {
  const client = new Client({ connectionString: DB_URL })
  await client.connect()

  try {
    await client.query(
      // movimento_bancario entra explicitamente: ele e referenciado POR
      // parcela, entao o cascade de operacao_credito nao o alcanca — sem
      // isto o documento unico de uma execucao anterior sobrevive e a
      // proxima falha com "ja existe um movimento".
      'truncate capital_ledger, operacao_credito, esc_capital_social, movimento_bancario cascade',
    )
    await client.query("delete from tomador where cnpj like '9999%'")
    await client.query("delete from usuario where email = 'e2e-operador@orgcred.test'")

    const usuarioId = randomUUID()
    await client.query(
      `insert into usuario (id, email, nome, papel, ativo) values ($1, $2, $3, $4, $5)`,
      [usuarioId, 'e2e-operador@orgcred.test', 'Admin E2E', 'admin', true],
    )

    await client.query(
      `insert into esc_capital_social (valor, tipo_evento) values (50000, 'constituicao')`,
    )

    const tomador = await client.query<{ id: string }>(
      `insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
       values ($1, 'Padaria Atrasada ME', 'ME', 'Formoso', 'GO', true) returning id`,
      [`9999${String(Date.now()).slice(-10)}`],
    )

    const op = await client.query<{ id: string }>(
      `insert into operacao_credito
        (tomador_id, tipo, valor_principal, taxa_juros_mensal, sistema_amortizacao,
         numero_parcelas, status, registro_entidade_ref)
       values ($1, 'emprestimo', 10000, 2.0, 'PRICE', 10, 'registrada', 'REG-E2E-AGING')
       returning id`,
      [tomador.rows[0].id],
    )
    const operacaoAtrasadaId = op.rows[0].id

    // Ativar gera a agenda (trigger da 007) e o evento de estado (008).
    await client.query(`update operacao_credito set status = 'ativa' where id = $1`, [
      operacaoAtrasadaId,
    ])

    await client.query('alter table parcela disable trigger trg_parcela_imutavel')
    await client.query(
      `update parcela set vencimento = current_date - 120
       where operacao_id = $1 and numero = 1`,
      [operacaoAtrasadaId],
    )
    await client.query('alter table parcela enable trigger trg_parcela_imutavel')

    const accessToken = jwt.sign(
      {
        sub: usuarioId,
        email: 'e2e-operador@orgcred.test',
        role: 'authenticated',
        aud: 'authenticated',
      },
      DEV_JWT_SECRET,
      { algorithm: 'HS256', expiresIn: '1h' },
    )

    return { usuarioId, accessToken, operacaoAtrasadaId }
  } finally {
    await client.end()
  }
}

export interface CenarioGeografico {
  usuarioId: string
  accessToken: string
  /** Registrada, com capital de sobra e registro presente — se for barrada,
   *  só pode ser pelo município (OC002). */
  operacaoForaDaAreaId: string
}

/**
 * Cenário isolado para o gate geográfico do Art. 5º.
 *
 * Vive em função separada de propósito: `semearCenarioAtivacao` é usada por
 * um teste que conta botões "Ativar" na tela, então acrescentar operações
 * àquele cenário quebra a contagem. Cada cenário semeia seu próprio mundo —
 * os testes rodam em série (ver playwright.config.ts) justamente porque o
 * seed trunca as tabelas.
 */
export async function semearCenarioGeografico(): Promise<CenarioGeografico> {
  const client = new Client({ connectionString: DB_URL })
  await client.connect()

  try {
    await client.query(
      // movimento_bancario entra explicitamente: ele e referenciado POR
      // parcela, entao o cascade de operacao_credito nao o alcanca — sem
      // isto o documento unico de uma execucao anterior sobrevive e a
      // proxima falha com "ja existe um movimento".
      'truncate capital_ledger, operacao_credito, esc_capital_social, movimento_bancario cascade',
    )
    await client.query("delete from tomador where cnpj like '9999%'")
    await client.query("delete from usuario where email = 'e2e-operador@orgcred.test'")

    const usuarioId = randomUUID()
    await client.query(
      `insert into usuario (id, email, nome, papel, ativo) values ($1, $2, $3, $4, $5)`,
      [usuarioId, 'e2e-operador@orgcred.test', 'Operador E2E', 'operador', true],
    )

    // Capital farto: garante que um eventual bloqueio NAO venha do teto.
    await client.query(
      `insert into esc_capital_social (valor, tipo_evento) values (50000, 'constituicao')`,
    )

    const tomadorFora = await client.query<{ id: string }>(
      `insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
       values ($1, 'Mercado Fora da Area ME', 'ME', 'Sao Paulo', 'SP', false) returning id`,
      [`9999${String(Date.now()).slice(-10)}`],
    )

    const opFora = await client.query<{ id: string }>(
      `insert into operacao_credito
        (tomador_id, tipo, valor_principal, taxa_juros_mensal, sistema_amortizacao,
         numero_parcelas, status, registro_entidade_ref)
       values ($1, 'emprestimo', 1000, 2.0, 'PRICE', 6, 'registrada', 'REG-E2E-FORA')
       returning id`,
      [tomadorFora.rows[0].id],
    )

    const accessToken = jwt.sign(
      {
        sub: usuarioId,
        email: 'e2e-operador@orgcred.test',
        role: 'authenticated',
        aud: 'authenticated',
      },
      DEV_JWT_SECRET,
      { algorithm: 'HS256', expiresIn: '1h' },
    )

    return { usuarioId, accessToken, operacaoForaDaAreaId: opFora.rows[0].id }
  } finally {
    await client.end()
  }
}
