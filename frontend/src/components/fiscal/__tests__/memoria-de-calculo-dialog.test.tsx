import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ApiError } from '@/api/errors'
import { MemoriaDeCalculoDialog } from '@/components/fiscal/memoria-de-calculo-dialog'
import type { MemoriaCalculo } from '@/components/fiscal/memoria'
import {
  MEMORIA_COM_ADICIONAL,
  MEMORIA_CONFERE,
  MEMORIA_DIVERGENTE,
} from '@/components/fiscal/__tests__/fixtures'

const { buscarMock } = vi.hoisted(() => ({ buscarMock: vi.fn() }))

// Só a chamada de rede é dublada. As serializações (texto e CSV) rodam de
// verdade: o que este arquivo precisa provar sobre "levar para fora" é que o
// conteúdo real chega ao clipboard e ao arquivo.
vi.mock('@/components/fiscal/memoria-api', () => ({ buscarMemoriaDeCalculo: buscarMock }))

function renderDialog() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <MemoriaDeCalculoDialog apuracaoId="apuracao-1" rotulo="1º tri/2026" />
    </QueryClientProvider>,
  )
}

async function abrir() {
  renderDialog()
  await userEvent.click(screen.getByRole('button', { name: /Memória de cálculo/ }))
}

function linhaDe(tributo: string) {
  return screen.getByText(tributo).closest('tr') as HTMLElement
}

describe('MemoriaDeCalculoDialog', () => {
  beforeEach(() => {
    buscarMock.mockReset()
    buscarMock.mockResolvedValue(MEMORIA_CONFERE)
  })

  it('não busca a memória enquanto o diálogo está fechado', () => {
    renderDialog()
    // A lista de apurações não pode carregar a memória de todo trimestre só
    // para desenhar os botões.
    expect(buscarMock).not.toHaveBeenCalled()
  })

  it('mostra o estado de carregando antes de a memória chegar', async () => {
    let liberar!: (m: MemoriaCalculo) => void
    buscarMock.mockImplementation(
      () =>
        new Promise<MemoriaCalculo>((resolve) => {
          liberar = resolve
        }),
    )
    await abrir()

    // Sem placeholder, o diálogo abre vazio e parece uma apuração que não tem
    // memória — o contador fecha antes de a resposta chegar.
    await waitFor(() => expect(document.querySelector('[data-slot="skeleton"]')).toBeTruthy())
    expect(screen.queryByRole('table')).not.toBeInTheDocument()

    liberar(MEMORIA_CONFERE)

    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(document.querySelector('[data-slot="skeleton"]')).toBeNull()
  })

  it('mostra a derivação de cada tributo, linha a linha', async () => {
    await abrir()

    const irpj = await waitFor(() => linhaDe('IRPJ'))
    const celulas = within(irpj).getAllByRole('cell')
    // Receita considerada -> presunção -> base -> alíquota -> valor.
    expect(celulas[1]).toHaveTextContent('10.000,00')
    expect(celulas[2]).toHaveTextContent('32,00%')
    expect(celulas[3]).toHaveTextContent('3.200,00')
    expect(celulas[4]).toHaveTextContent('15,00%')
    expect(celulas[5]).toHaveTextContent('480,00')
  })

  it('mostra travessão na presunção de PIS e COFINS, não zero', async () => {
    await abrir()

    const pis = await waitFor(() => linhaDe('PIS'))
    const celulas = within(pis).getAllByRole('cell')
    // Presunção é conceito de IRPJ/CSLL; "0,00%" ali afirmaria uma presunção
    // de zero por cento — e a base exibida seria mentira, porque é a receita.
    expect(celulas[2]).toHaveTextContent('—')
    expect(celulas[3]).toHaveTextContent('10.000,00')
  })

  it('explica o adicional zerado pelo limite, em vez de exibir só R$ 0,00', async () => {
    await abrir()

    const adicional = await waitFor(() => linhaDe('Adicional de IRPJ'))
    expect(adicional).toHaveTextContent(/abaixo do limite de R\$\s?60\.000,00/)
    expect(within(adicional).getAllByRole('cell')[5]).toHaveTextContent('0,00')
  })

  it('mostra base, limite e excedente quando o adicional incide', async () => {
    buscarMock.mockResolvedValue(MEMORIA_COM_ADICIONAL)
    await abrir()

    const adicional = await waitFor(() => linhaDe('Adicional de IRPJ'))
    expect(adicional).toHaveTextContent(/excedente/)
    expect(adicional).toHaveTextContent(/80\.000,00/)
    expect(adicional).toHaveTextContent(/60\.000,00/)
    // A base do adicional exibida é o EXCEDENTE, porque é sobre ele que a
    // alíquota incide — mostrar 80.000,00 x 10% daria 8.000,00, e o valor ao
    // lado seria 2.000,00 sem explicação nenhuma.
    expect(within(adicional).getAllByRole('cell')[3]).toHaveTextContent('20.000,00')
    expect(within(adicional).getAllByRole('cell')[5]).toHaveTextContent('2.000,00')
  })

  it('denuncia a divergência entre o recalculado e o gravado', async () => {
    buscarMock.mockResolvedValue(MEMORIA_DIVERGENTE)
    await abrir()

    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent('O recálculo não reproduz os valores gravados')
    // A providência precisa aparecer: OC016 impede editar a linha.
    expect(alerta).toHaveTextContent(/versão retificadora/)
    expect(alerta).toHaveTextContent(/recalculado R\$\s?480,00, gravado R\$\s?999,99/)

    // E a linha do tributo é marcada, para a tela não obrigar ninguém a cruzar
    // a lista de divergências com a tabela.
    expect(linhaDe('IRPJ')).toHaveTextContent('Diverge')
    expect(linhaDe('CSLL')).not.toHaveTextContent('Diverge')
  })

  it('não inventa alerta quando a memória confere', async () => {
    await abrir()

    await waitFor(() => linhaDe('IRPJ'))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('copia a memória com a derivação, não só os totais', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    await abrir()

    await waitFor(() => linhaDe('IRPJ'))
    await userEvent.click(screen.getByRole('button', { name: /Copiar memória/ }))

    const copiado = writeText.mock.calls[0][0] as string
    expect(copiado).toContain('receita 10000,00 x presunção 32,0000% = base 3200,00')
    expect(copiado).toContain('base 3200,00 x 15,0000% = 480,00')
    vi.unstubAllGlobals()
  })

  it('avisa quando a área de transferência é negada, em vez de falhar calado', async () => {
    vi.stubGlobal('navigator', {
      ...navigator,
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error('negado')) },
    })
    await abrir()

    await waitFor(() => linhaDe('IRPJ'))
    await userEvent.click(screen.getByRole('button', { name: /Copiar memória/ }))

    // Sem isto, o contador colaria o conteúdo antigo sem saber por quê.
    expect(await screen.findByRole('status')).toHaveTextContent(/Não foi possível copiar/)
    vi.unstubAllGlobals()
  })

  it('entrega o CSV por âncora ligada ao documento, com nome do período', async () => {
    const criarUrl = vi.fn((_blob: Blob) => 'blob:memoria')
    vi.stubGlobal('URL', { ...URL, createObjectURL: criarUrl, revokeObjectURL: vi.fn() })
    // Um <a> desconectado não dispara download no Firefox: o clique tem que
    // acontecer com a âncora dentro do documento.
    let ligadaNoClique = false
    const clique = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      ligadaNoClique = this.isConnected
    })

    await abrir()
    await waitFor(() => linhaDe('IRPJ'))
    await userEvent.click(screen.getByRole('button', { name: /Baixar CSV/ }))

    expect(criarUrl).toHaveBeenCalled()
    expect(ligadaNoClique).toBe(true)
    expect(document.querySelector('a[download]')).toBeNull()

    const blob = criarUrl.mock.calls[0][0]
    // BOM conferido em BYTES, e não pelo texto: `Blob.text()` decodifica UTF-8
    // e descarta o BOM inicial, então a asserção sobre a string passaria com e
    // sem ele. Sem BOM, o Excel em pt-BR abre o CSV em Latin-1 e "Apuração"
    // vira lixo na primeira coluna de um documento fiscal.
    const bytes = new Uint8Array(await blob.arrayBuffer())
    expect([bytes[0], bytes[1], bytes[2]]).toEqual([0xef, 0xbb, 0xbf])

    const conteudo = await blob.text()
    expect(conteudo).toContain('IRPJ;10000,00;32,0000%;3200,00;;;15,0000%;480,00;480,00;sim')

    clique.mockRestore()
    vi.unstubAllGlobals()
  })

  it('adia a revogação da URL do blob para não abortar a própria gravação', async () => {
    const revogar = vi.fn()
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:memoria'),
      revokeObjectURL: revogar,
    })
    const clique = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    await abrir()
    await waitFor(() => linhaDe('IRPJ'))

    vi.useFakeTimers()
    fireEvent.click(screen.getByRole('button', { name: /Baixar CSV/ }))

    // Revogar na mesma volta do event loop aborta a gravação no Chromium, e o
    // download some sem nada na tela. A URL só pode cair depois.
    expect(revogar).not.toHaveBeenCalled()
    vi.advanceTimersByTime(60_000)
    expect(revogar).toHaveBeenCalledWith('blob:memoria')

    vi.useRealTimers()
    clique.mockRestore()
    vi.unstubAllGlobals()
  })

  it('anuncia a falha de carregamento em região viva', async () => {
    buscarMock.mockRejectedValue(new ApiError('Apuração fiscal não encontrada.', null, 404))
    await abrir()

    expect(await screen.findByRole('alert')).toHaveTextContent('Apuração fiscal não encontrada.')
  })
})
