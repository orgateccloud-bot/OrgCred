# Arte-fonte

Originais de onde os assets publicados são derivados. **Nada aqui é servido
pelo frontend** — o que vai para o navegador está em `frontend/public/`.

## `orgatec-logo-original.png`

Logotipo da Orgatec como recebido: 1024×1024, RGBA mas com **alpha 255 em
todos os pixels** (fundo preto opaco, não transparente), marca ocupando só a
faixa central e a tagline "O parceiro financeiro da sua empresa" embutida na
imagem.

Usado direto, isso dá dois problemas: bloco preto no tema claro, e marca
ilegível em tamanho de UI, porque a tagline consome metade da altura
disponível.

`frontend/public/orgatec-logo.png` é derivado dele assim:

1. **Recorte** em `(80, 218, 932, 590)` — só o wordmark. A tagline é um bloco
   separado que começa em `y=608` e vira ruído em qualquer tamanho de tela.
2. **Alpha por luminância** com rampa suave entre 8 e 44: preto vira
   transparente, a marca fica opaca, e as bordas antisserrilhadas são
   preservadas. Corte seco deixaria serrilhado visível.
3. **Redução para 50%** (426×186), com LANCZOS — o dobro do maior uso em tela.

Reproduzir com Pillow; o script está no histórico do commit que adicionou o
logo.

## Limitação conhecida

A fita prateada da marca é branca e **some no tema claro**. É característica
do desenho, feito para fundo escuro — não tem solução por processamento.
Resolver de verdade exige uma variante para fundo claro (fita em tom escuro)
ou um SVG em que a cor possa ser trocada por tema.
