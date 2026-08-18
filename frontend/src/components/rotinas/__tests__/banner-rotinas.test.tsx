import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BannerRotinas } from '@/components/rotinas/banner-rotinas'
import {
  descreverAtraso,
  rotinasComProblema,
  rotuloRotina,
  type EstadoRotina,
  type EstadoRotinas,
} from '@/components/rotinas/estado-rotinas'

function rotina(parcial: Partial<EstadoRotina> & { rotina: string }): EstadoRotina {
  return {
    ultima_tentativa: '2026-08-18T03:00:00Z',
    ultima_execucao: '2026-08-18T03:00:00Z',
    iniciada_em: '2026-08-18T02:59:00Z',
    duracao_s: '60.000',
    resultado: 'sucesso',
    erro: null,
    detalhe: {},
    ultimo_sucesso: '2026-08-18T03:00:00Z',
    horas_desde_ultimo_sucesso: 2,
    limite_horas: 36,
    atrasada: false,
    falhou: false,
    nunca_executou: false,
    ...parcial,
  }
}

function estado(rotinas: EstadoRotina[], saudavel: boolean): EstadoRotinas {
  return { verificado_em: '2026-08-18T12:00:00Z', saudavel, rotinas }
}

describe('BannerRotinas', () => {
  it('some quando as rotinas estão em dia', () => {
    const { container } = render(
      <BannerRotinas
        estado={estado(
          [
            rotina({ rotina: 'aging' }),
            rotina({ rotina: 'backup', horas_desde_ultimo_sucesso: 30 }),
          ],
          true,
        )}
      />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it('some enquanto o estado ainda não chegou', () => {
    // Sem dado não se afirma nem saúde nem incidente: a leitura do estado das
    // rotinas é a única query do dashboard que pode falhar sem apagar a tela,
    // e um banner otimista aqui seria pior que nenhum.
    const { container } = render(<BannerRotinas />)

    expect(container).toBeEmptyDOMElement()
  })

  it('aparece com a rotina que parou de rodar, mesmo sem nenhuma falha', () => {
    // O CASO PERIGOSO: nunca falhou, e há nove dias não roda. Não existe
    // execução vermelha em lugar nenhum — só a distância.
    render(
      <BannerRotinas
        estado={estado(
          [
            rotina({ rotina: 'aging', horas_desde_ultimo_sucesso: 216, atrasada: true }),
            rotina({ rotina: 'backup' }),
          ],
          false,
        )}
      />,
    )

    const aviso = screen.getByRole('status')
    expect(aviso).toHaveTextContent('Uma rotina periódica não está em dia')
    expect(aviso).toHaveTextContent('Régua de inadimplência')
    expect(aviso).toHaveTextContent('sem sucesso há 9 dias')
    expect(aviso).toHaveTextContent('limite: 36h')
    // A rotina saudável não entra na lista: o aviso é sobre o que está errado.
    expect(aviso).not.toHaveTextContent('Backup do banco')
  })

  it('mostra a mensagem de erro da rotina que falhou na última execução', () => {
    render(
      <BannerRotinas
        estado={estado(
          [
            rotina({
              rotina: 'backup',
              resultado: 'falha',
              falhou: true,
              erro: 'RotinaError: backup.sh saiu com código 2: disco cheio',
              horas_desde_ultimo_sucesso: 5,
            }),
          ],
          false,
        )}
      />,
    )

    const aviso = screen.getByRole('status')
    expect(aviso).toHaveTextContent('Backup do banco')
    expect(aviso).toHaveTextContent('disco cheio')
  })

  it('nomeia "nunca executou" em vez de inventar uma distância', () => {
    render(
      <BannerRotinas
        estado={estado(
          [
            rotina({
              rotina: 'restore_test',
              ultima_execucao: null,
              ultimo_sucesso: null,
              horas_desde_ultimo_sucesso: null,
              limite_horas: 1080,
              atrasada: true,
              nunca_executou: true,
            }),
          ],
          false,
        )}
      />,
    )

    const aviso = screen.getByRole('status')
    expect(aviso).toHaveTextContent('Teste de restauração do backup')
    expect(aviso).toHaveTextContent('nunca executou')
    expect(aviso).toHaveTextContent('limite: 45 dias')
  })

  it('conta as rotinas no plural quando há mais de uma', () => {
    render(
      <BannerRotinas
        estado={estado(
          [
            rotina({ rotina: 'aging', atrasada: true, horas_desde_ultimo_sucesso: 40 }),
            rotina({ rotina: 'backup', falhou: true, erro: 'x', horas_desde_ultimo_sucesso: 3 }),
          ],
          false,
        )}
      />,
    )

    expect(screen.getByRole('status')).toHaveTextContent('2 rotinas periódicas não estão em dia')
  })

  it('não afirma incidente sem ter o que listar', () => {
    // `saudavel: false` com lista vazia só pode ser resposta malformada. Um
    // banner vermelho sem nenhuma rotina nomeada não dá nada a fazer.
    const { container } = render(<BannerRotinas estado={estado([], false)} />)

    expect(container).toBeEmptyDOMElement()
  })

  it('não reabre o julgamento quando o backend diz que está saudável', () => {
    // Quem decide o que é atraso é `app/rotinas.LIMITE_ATRASO_HORAS`, lido pelo
    // endpoint — e `saudavel` é essa decisão. Uma resposta em que `saudavel` é
    // verdadeiro e uma rotina vem marcada como atrasada só pode ser contradição
    // de contrato, e a tela obedece ao veredito em vez de arbitrar com os
    // campos soltos. Sem esta asserção, apagar a guarda de `saudavel` do
    // componente não quebra teste nenhum — e a régua passa a existir em dois
    // lugares, que é exatamente o que o cabeçalho do banner promete não fazer.
    const { container } = render(
      <BannerRotinas estado={estado([rotina({ rotina: 'aging', atrasada: true })], true)} />,
    )

    expect(container).toBeEmptyDOMElement()
  })
})

describe('rotinasComProblema', () => {
  it('põe quem parou de rodar antes de quem falhou', () => {
    // A falha já se anuncia sozinha (execução vermelha, mensagem de erro); a
    // ausência de execução não se anuncia por nada. Ordenar por falha primeiro
    // empurraria para o fim exatamente o caso que ninguém tem como descobrir.
    const problemas = rotinasComProblema(
      estado(
        [
          rotina({ rotina: 'backup', falhou: true, erro: 'x', horas_desde_ultimo_sucesso: 3 }),
          rotina({ rotina: 'aging', atrasada: true, horas_desde_ultimo_sucesso: 216 }),
          rotina({
            rotina: 'restore_test',
            atrasada: true,
            nunca_executou: true,
            horas_desde_ultimo_sucesso: null,
          }),
        ],
        false,
      ),
    )

    expect(problemas.map((r) => r.rotina)).toEqual(['restore_test', 'aging', 'backup'])
  })

  it('deixa de fora a rotina sem limiar declarado que nunca é dada como atrasada', () => {
    const problemas = rotinasComProblema(
      estado([rotina({ rotina: 'faxina_experimental', limite_horas: null })], false),
    )

    expect(problemas).toEqual([])
  })
})

describe('descreverAtraso', () => {
  it('usa horas abaixo de 48h', () => {
    // A faixa de decisão das diárias é 36h: "1 dia" apagaria a diferença entre
    // 30h (normal) e 40h (atrasada).
    expect(descreverAtraso(30)).toBe('sem sucesso há 30h')
    expect(descreverAtraso(40)).toBe('sem sucesso há 40h')
  })

  it('usa dias a partir de 48h', () => {
    expect(descreverAtraso(216)).toBe('sem sucesso há 9 dias')
  })

  it('nunca executou não vira "há 0h"', () => {
    expect(descreverAtraso(null)).toBe('nunca executou')
  })
})

describe('rotuloRotina', () => {
  it('traduz as quatro rotinas conhecidas', () => {
    expect(rotuloRotina('aging')).toBe('Régua de inadimplência')
    expect(rotuloRotina('atipicidades')).toBe('Varredura de atipicidade (PLD)')
    expect(rotuloRotina('backup')).toBe('Backup do banco')
    expect(rotuloRotina('restore_test')).toBe('Teste de restauração do backup')
  })

  it('mostra o nome cru de uma rotina que o painel não conhece', () => {
    expect(rotuloRotina('faxina_experimental')).toBe('faxina_experimental')
  })
})
