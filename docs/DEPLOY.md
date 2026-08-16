# Deploy — configuração versionada

## `railway.json`

A configuração de deploy vive no repositório, não no painel. Antes disso, cada
serviço novo nascia com o que o Railway adivinhasse: foi assim que um serviço
duplicado nasceu com builder **Railpack** em vez do nosso `Dockerfile`, subiu um
processo que terminava sozinho e ficou marcado como `Completed` — parecendo
saudável.

### `healthcheckPath: /health/ready`, e não `/health`

Os dois existem e respondem coisas diferentes:

| Rota | Responde | Prova |
|---|---|---|
| `/health` | dicionário literal | que o processo subiu |
| `/health/ready` | faz `SELECT 1` no banco | que a aplicação **serve** |

O serviço apontava para `/health`. Um contêiner que sobe sem alcançar o Postgres
— credencial errada, banco fora, rede — passava no health check e era promovido
a ativo. O deploy ficava verde e a aplicação, inútil.

Com `/health/ready`, um deploy que não alcança o banco **falha e não substitui o
anterior**. É o comportamento que se quer: preferir a versão antiga funcionando
à versão nova quebrada.

O preço: se o Postgres estiver momentaneamente fora no instante do deploy, o
deploy falha. É deliberado — falhar cedo e visível é melhor que promover um
contêiner que não serve.

### `healthcheckTimeout: 120`

O `CMD` roda `alembic upgrade head` antes do uvicorn. Numa migration pesada o
primeiro `/health/ready` pode demorar; 120s dá margem sem mascarar contêiner
travado.

### `restartPolicyType: ON_FAILURE`, 3 tentativas

`ALWAYS` reiniciaria em loop um contêiner que não tem como subir — por exemplo,
quando a guarda fail-closed recusa iniciar por configuração ausente
(`app/core/config.py`). Nesse caso reiniciar não conserta nada e só esconde a
causa no volume de log. Três tentativas cobrem falha transitória; além disso, o
deploy fica `FAILED`, que é a informação correta.

## O que este arquivo NÃO resolve

**As migrations continuam no `CMD`** (`Dockerfile:69`), e não numa fase de
pré-deploy separada. Consequências, que seguem valendo:

- com mais de uma réplica, duas instâncias correm `alembic upgrade head` contra
  o mesmo banco ao mesmo tempo;
- uma migration que falhe no meio deixa o schema parcialmente aplicado e o
  contêiner em loop de restart;
- reverter o código não reverte o schema — o banco fica adiantado em relação à
  imagem anterior.

Mover para `preDeployCommand` resolve, mas muda **como as migrations chegam à
produção** e merece ser feito e verificado por si, não de carona.

**Variável nova não recria o contêiner.** Gravar variável pelo painel ou pela
API **não** dispara redeploy sozinho: ela fica pendente até o próximo deploy.
Foi o que aconteceu com `ORGCRED_ENVIRONMENT=production`, que ficou gravada e
inerte por horas. Depois de mexer em variável, force um deploy — um push em
`main` basta, e é preferível a subir tarball, que faz o deploy perder o hash de
commit.
