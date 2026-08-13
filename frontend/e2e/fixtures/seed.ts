import { randomUUID } from 'node:crypto'
import { Client } from 'pg'
import jwt from 'jsonwebtoken'

const DEV_JWT_SECRET = 'dev-secret-key-change-in-prod' // mesma secret do docker-compose.yml (dev only)
const DB_URL =
  process.env.E2E_DATABASE_URL ??
  'postgresql://orgcred:orgcred_dev_password@localhost:5433/orgcred_dev'

/**
 * Confirma o registro em entidade registradora de uma operação.
 *
 * Desde a migration 013 o gate do Art. 5º §3º exige registro CONFIRMADO
 * para ativar — `registro_entidade_ref` de texto livre deixou de bastar.
 * Todo cenário que ativa (ou que oferece o botão Ativar) passa por aqui.
 */
async function confirmarRegistro(client: Client, operacaoId: string, entidade = 'CRDC') {
  await client.query(
    `insert into registro_operacao (operacao_id, entidade, status, protocolo, confirmado_em)
     values ($1, $2, 'confirmado', $3, now())`,
    [operacaoId, entidade, `PROTO-E2E-${operacaoId.slice(0, 8)}`],
  )
}

/**
 * Arquiva uma evidência de identificação para o tomador.
 *
 * Desde a migration 014, ativar exige ao menos uma evidência arquivada
 * (Lei 9.613/98, art. 10, I). Vale inclusive para os cenários que testam
 * OUTROS bloqueios: sem isto, o gate geográfico e o de teto passariam a
 * falhar por OC019 e deixariam de provar o que prometem.
 */
async function arquivarIdentificacao(client: Client, tomadorId: string) {
  await client.query(
    `insert into tomador_documento (tomador_id, tipo, nome_arquivo, sha256, retencao_ate)
     values ($1, 'contrato_social', 'contrato-e2e.pdf', encode(digest($2, 'sha256'), 'hex'),
             current_date + interval '5 years')`,
    [tomadorId, `e2e:${tomadorId}`],
  )
}

/**
 * Zera as tabelas do cenário no banco de DESENVOLVIMENTO.
 *
 * Desde a migration 016, `capital_ledger` e `esc_capital_social` recusam
 * TRUNCATE por trigger de statement (as guardas append-only anteriores eram
 * por LINHA, e TRUNCATE passava por baixo delas). Ou seja: apagar a trilha
 * exige desligar a proteção com nome e sobrenome, e é isso que este helper
 * faz — de propósito verboso, porque a dificuldade é a prova de que pela
 * aplicação não existe caminho para destruir o histórico.
 */
async function zerarCenario(client: Client) {
  await client.query('alter table capital_ledger disable trigger trg_bloquear_truncate_ledger')
  await client.query(
    'alter table esc_capital_social disable trigger trg_bloquear_truncate_capital_social',
  )
  await client.query('alter table operacao_evento disable trigger trg_bloquear_truncate_evento')
  // O `cascade` alcança estas duas por chave estrangeira, então elas também
  // recebem o TRUNCATE e disparam a própria guarda.
  await client.query('alter table tomador_documento disable trigger trg_bloquear_truncate_documento')
  await client.query(
    'alter table ocorrencia_atipicidade disable trigger trg_bloquear_truncate_ocorrencia',
  )
  try {
    // movimento_bancario entra explicitamente: ele é referenciado POR parcela,
    // então o cascade de operacao_credito não o alcança — sem isto o documento
    // único de uma execução anterior sobrevive e a próxima falha com "já existe
    // um movimento".
    await client.query(
      'truncate capital_ledger, operacao_credito, esc_capital_social, movimento_bancario cascade',
    )
  } finally {
    await client.query('alter table capital_ledger enable trigger trg_bloquear_truncate_ledger')
    await client.query(
      'alter table esc_capital_social enable trigger trg_bloquear_truncate_capital_social',
    )
    await client.query('alter table operacao_evento enable trigger trg_bloquear_truncate_evento')
    await client.query(
      'alter table tomador_documento enable trigger trg_bloquear_truncate_documento',
    )
    await client.query(
      'alter table ocorrencia_atipicidade enable trigger trg_bloquear_truncate_ocorrencia',
    )
  }
}

/**
 * Limpa os tomadores de teste e o que pende deles.
 *
 * `tomador_documento` está sob retenção legal (OC013) e
 * `ocorrencia_atipicidade` é append-only (OC014): apagar exige desligar os
 * guards explicitamente. Ter que fazer isso é justamente a prova de que,
 * pela aplicação, não existe caminho para destruir essas trilhas.
 */
async function limparTomadoresDeTeste(client: Client) {
  await client.query('alter table tomador_documento disable trigger trg_documento_retencao')
  await client.query(
    'alter table ocorrencia_atipicidade disable trigger trg_ocorrencia_append_only',
  )
  await client.query(
    `delete from tomador_documento
      where tomador_id in (select id from tomador where cnpj like '9999%')`,
  )
  await client.query(
    `delete from ocorrencia_atipicidade
      where tomador_id in (select id from tomador where cnpj like '9999%')`,
  )
  await client.query('alter table tomador_documento enable trigger trg_documento_retencao')
  await client.query('alter table ocorrencia_atipicidade enable trigger trg_ocorrencia_append_only')
  await client.query("delete from tomador where cnpj like '9999%'")
}

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
    await zerarCenario(client)
    await limparTomadoresDeTeste(client)
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
    await arquivarIdentificacao(client, tomadorId)

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

    // As duas precisam de registro confirmado: a segunda tem que ser
    // barrada pelo TETO (OC001), não pela falta de registro (OC004).
    await confirmarRegistro(client, opAtivavel.rows[0].id)
    await confirmarRegistro(client, opBloqueada.rows[0].id)

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
    await zerarCenario(client)
    await limparTomadoresDeTeste(client)
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

    await arquivarIdentificacao(client, tomador.rows[0].id)

    const op = await client.query<{ id: string }>(
      `insert into operacao_credito
        (tomador_id, tipo, valor_principal, taxa_juros_mensal, sistema_amortizacao,
         numero_parcelas, status, registro_entidade_ref)
       values ($1, 'emprestimo', 10000, 2.0, 'PRICE', 10, 'registrada', 'REG-E2E-AGING')
       returning id`,
      [tomador.rows[0].id],
    )
    const operacaoAtrasadaId = op.rows[0].id

    await confirmarRegistro(client, operacaoAtrasadaId)

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
    await zerarCenario(client)
    await limparTomadoresDeTeste(client)
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

    // O tomador fora da área também precisa de identificação: senão o
    // bloqueio viria de OC019 e o cenário deixaria de provar OC002.
    await arquivarIdentificacao(client, tomadorFora.rows[0].id)

    const opFora = await client.query<{ id: string }>(
      `insert into operacao_credito
        (tomador_id, tipo, valor_principal, taxa_juros_mensal, sistema_amortizacao,
         numero_parcelas, status, registro_entidade_ref)
       values ($1, 'emprestimo', 1000, 2.0, 'PRICE', 6, 'registrada', 'REG-E2E-FORA')
       returning id`,
      [tomadorFora.rows[0].id],
    )

    // Sem registro confirmado o bloqueio viria de OC004 e o cenário deixaria
    // de provar o que promete (OC002, gate geográfico).
    await confirmarRegistro(client, opFora.rows[0].id)

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

export interface CenarioSemIdentificacao {
  usuarioId: string
  accessToken: string
  tomadorId: string
  razaoSocial: string
}

/**
 * Tomador cadastrado e SEM nenhuma evidência de identificação arquivada.
 *
 * É o estado em que todo tomador criado pela interface nasce, e o que o gate
 * OC019 (migration 014) recusa ativar. Serve para exercitar a seção de
 * Identificação da ficha: o vazio que avisa do bloqueio, e o upload real —
 * cujo corpo multipart é inspecionado na rede, já que sem `service_role` key
 * o servidor responde 503 antes de processar o arquivo.
 */
export async function semearTomadorSemIdentificacao(): Promise<CenarioSemIdentificacao> {
  const client = new Client({ connectionString: DB_URL })
  await client.connect()

  try {
    await zerarCenario(client)
    await limparTomadoresDeTeste(client)
    await client.query("delete from usuario where email = 'e2e-operador@orgcred.test'")

    const usuarioId = randomUUID()
    await client.query(
      `insert into usuario (id, email, nome, papel, ativo) values ($1, $2, $3, $4, $5)`,
      [usuarioId, 'e2e-operador@orgcred.test', 'Operador E2E', 'admin', true],
    )

    const razaoSocial = 'Mercearia Sem Documento ME'
    const tomador = await client.query<{ id: string }>(
      `insert into tomador (cnpj, razao_social, porte, municipio, uf, municipio_autorizado)
       values ($1, $2, 'ME', 'Formoso', 'GO', true) returning id`,
      [`9999${String(Date.now()).slice(-10)}`, razaoSocial],
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

    return { usuarioId, accessToken, tomadorId: tomador.rows[0].id, razaoSocial }
  } finally {
    await client.end()
  }
}

/**
 * Baixa TODAS as parcelas da operação contra movimento bancário.
 *
 * Desde a migration 017, `ativa -> liquidada` só passa com a agenda inteira
 * baixada (OC022) — quitação exige provar o pagamento. Espelha o helper
 * `quitar_operacao` de tests/conftest.py, deliberadamente: se a regra de
 * lastro mudar, os dois têm que mudar juntos, e ter o mesmo formato torna a
 * divergência visível.
 *
 * Devolve quantas parcelas foram baixadas; zero significa operação sem
 * agenda, cenário que a 017 recusa liquidar de propósito.
 */
export async function quitarOperacao(operacaoId: string): Promise<number> {
  const client = new Client({ connectionString: DB_URL })
  await client.connect()

  try {
    const parcelas = await client.query<{ id: string; valor_total: string }>(
      'select id, valor_total from parcela where operacao_id = $1 order by numero',
      [operacaoId],
    )

    for (const parcela of parcelas.rows) {
      const movimento = await client.query<{ id: string }>(
        `insert into movimento_bancario (data_movimento, valor, documento)
         values (current_date, $1, $2) returning id`,
        [parcela.valor_total, `FITID-QUIT-${parcela.id.slice(0, 12)}`],
      )
      await client.query('select fn_baixar_parcela($1, $2)', [parcela.id, movimento.rows[0].id])
    }

    return parcelas.rowCount ?? 0
  } finally {
    await client.end()
  }
}
