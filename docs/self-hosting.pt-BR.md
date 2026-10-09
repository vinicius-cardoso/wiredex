# Rodando o seu próprio Wiredex

[English](self-hosting.md) · **Português (Brasil)**

O Wiredex é feito para a bancada de uma pessoa, e roda em um servidor bem pequeno: a
instância em wiredex.vinilabs.cc é uma VM com menos de 1 GB de RAM. Este guia leva você de
um fork até uma cópia sua em funcionamento. O [deploy/README.pt-BR.md](../deploy/README.pt-BR.md)
é o runbook daquela instância, e é a referência quando um passo daqui precisa de mais detalhe.

Não há cadastro público nem modo multi-inquilino: você cria as contas pela linha de
comando, e cada conta recebe seu próprio workspace ([ADR 0008](adr/0008-sessions.md)).

## O que você precisa

| O quê | Por quê |
| --- | --- |
| Um servidor Linux com IP público; 1 GB de RAM ou menos é suficiente | Roda o Docker (Postgres e a API) e o Caddy |
| Um domínio apontando para ele | O Caddy obtém o certificado TLS para ele |
| Um bucket compatível com S3 e uma chave de acesso limitada a ele | Os anexos (datasheets, fotos, Gerbers) ficam lá, não no disco do servidor. Em produção a API se recusa a iniciar sem ele |
| Um fork deste repositório no GitHub | O workflow de release faz o build da imagem e o deploy |
| Um segundo bucket, opcional | Backups noturnos criptografados |

Qualquer armazenamento compatível com S3 serve: a instância usa o Oracle Cloud Object
Storage pela sua API S3, e MinIO, Backblaze B2 ou AWS S3 respondem às mesmas chamadas.

## Como as partes se encaixam

```
GitHub Actions (workflow Release)
  build ──► imagem da API ─► varredura do Trivy ─► ghcr.io/<você>/wiredex-api:<tag>
        └─► build da web (artefato)
  deploy ─► rsync para wiredex@host:/srv/wiredex ─► bin/deploy.sh <tag> ─► teste de fumaça
```

Nada é compilado no servidor. O Caddy serve o app web estático e repassa `/api/*` para o
contêiner da API; o Postgres roda ao lado, no Docker
([ADR 0009](adr/0009-single-host-deployment.md)).

## 1. Torne o fork seu

Quatro lugares citam a instância original. Mude-os no seu fork:

| Arquivo | O que mudar |
| --- | --- |
| `deploy/wiredex.caddy` | `wiredex.vinilabs.cc` na primeira linha do bloco do site, para o seu domínio |
| `deploy/compose.prod.yml` | `ghcr.io/vinicius-cardoso/wiredex-api`, para `ghcr.io/<seu-usuário>/wiredex-api` |
| `.github/workflows/release.yml` | O nome da imagem, e `https://wiredex.vinilabs.cc` no nome, na URL e no teste de fumaça do job de deploy |
| `README.md` | Os links para a instância no ar, se você publicar o seu fork |

Depois da primeira release, torne o pacote `wiredex-api` **público** na sua conta do GitHub
(Packages → o pacote → Package settings), para que o servidor possa baixá-lo sem token. A
imagem não contém segredos.

## 2. Aponte o domínio para o servidor

Adicione um registro `A` do seu domínio para o IP do servidor. Se o seu provedor de DNS
faz proxy do tráfego (a nuvem laranja da Cloudflare), desligue o proxy para esse registro:
o Caddy precisa responder ele mesmo ao desafio do certificado.

## 3. Dê ao GitHub uma forma de entrar

Crie uma chave SSH que só o deploy usa:

```bash
ssh-keygen -t ed25519 -f wiredex-deploy -C wiredex-deploy -N ""
```

No seu fork, em *Settings → Environments*, crie um ambiente chamado `production`
que faz deploy apenas a partir da `main`, com:

| Tipo | Nome | Valor |
| --- | --- | --- |
| Secret | `DEPLOY_SSH_KEY` | A chave privada (`wiredex-deploy`) |
| Secret | `DEPLOY_KNOWN_HOSTS` | A chave do servidor: `ssh-keyscan -t ed25519 <ip>`, conferida com uma impressão digital em que você confia |
| Variable | `DEPLOY_HOST` | O IP do servidor |
| Variable | `DEPLOY_USER` | `wiredex` |

## 4. Prepare o servidor

Um script instala o Docker, cria o usuário de deploy `wiredex` e `/srv/wiredex`, liga o
site ao Caddy, limita o journal e instala os jobs noturnos. Rode-o da sua máquina,
com a metade pública da chave do passo 3:

```bash
ssh <host> "sudo DEPLOY_PUBLIC_KEY='ssh-ed25519 AAAA… wiredex-deploy' bash -s" < deploy/server-setup.sh
```

É seguro rodá-lo de novo. Ele gera dois arquivos de segredos que nunca saem do servidor e
nunca são sobrescritos:

- `/srv/wiredex/.env`: o Postgres e o login do dono do esquema, apenas para o banco e
  para as migrações.
- `/srv/wiredex/api.env`: o login da API, com o papel restrito `wiredex_app`, ao qual o
  row-level security se aplica ([ADR 0007](adr/0007-workspace-isolation.md)).

O script espera que o Caddy já esteja instalado, e faz com que ele importe
`/etc/caddy/sites/*.caddy`. A parte de backup foi escrita para a Oracle Cloud (ela se
autentica como a própria VM); em outra nuvem, pule as variáveis de backup e veja
*Backups* abaixo.

## 5. Diga à API para onde vão os arquivos

Adicione o armazenamento de arquivos a `/srv/wiredex/api.env` no servidor. As seis
variáveis são obrigatórias em produção:

```bash
WIREDEX_FILE_STORE=s3
WIREDEX_FILES_ENDPOINT=https://<seu endpoint S3>
WIREDEX_FILES_REGION=<região>
WIREDEX_FILES_BUCKET=<bucket>
WIREDEX_FILES_ACCESS_KEY=<chave de acesso>
WIREDEX_FILES_SECRET_KEY=<chave secreta>
```

Use uma chave que alcance esse único bucket e nada mais. Mantenha o bucket privado: a API
transmite ela mesma cada arquivo, depois de verificar quem pede. Ligar o versionamento de
objetos com expiração de 30 dias para versões antigas dá a você um desfazer para um anexo
excluído.

## 6. Faça a release

Faça merge na `main` do seu fork. O release-please abre um PR de release; o merge dele
cria a tag da versão, faz o build e a varredura da imagem, faz o deploy e roda um teste de
fumaça ([ADR 0012](adr/0012-versioning-and-releases.md)). Um deploy leva cerca de três
minutos. As migrações do banco rodam sozinhas durante ele, e um deploy que falha na
verificação de prontidão volta para a release anterior.

Para fazer o deploy à mão, ou para voltar a uma tag mais antiga, rode o workflow *Release*
com a tag como entrada.

## 7. Crie a sua conta

```bash
ssh -t <host> sudo -u wiredex /srv/wiredex/bin/wiredex users create --email you@example.com --name "Your name"
```

Ele pede uma senha e cria a conta com um workspace próprio. Depois abra o seu
domínio e faça login.

## No dia a dia

Todo comando passa pelo mesmo wrapper, na imagem da release no ar:

| Para | Rode no servidor, como `sudo -u wiredex /srv/wiredex/bin/wiredex …` |
| --- | --- |
| Convidar alguém para uma bancada de demonstração própria | `demo invite --email friend@example.com --expires 7d`, ou *Compartilhar uma demo* no menu da conta |
| Recomeçar um workspace, mantendo a conta | `workspace clear --email you@example.com` |
| Recalcular os saldos de estoque a partir do livro-razão | `stock rebuild` |
| Excluir arquivos para os quais nada mais aponta | `files prune` (também roda toda noite) |

Um timer do systemd reinicia as bancadas de demonstração e limpa os arquivos toda noite.
Confira com `journalctl -u wiredex-demo-reset --since today`.

Um comando roda no seu próprio computador, porque o servidor não tem espaço para um
toolchain: `wiredex firmware build`, que compila uma versão publicada de um firmware e
armazena os binários com ela, de modo que *Gravar pelo navegador* não precise de nenhum
arquivo escolhido. Ele precisa de um checkout deste repositório com `make install` feito, e
do [`arduino-cli`](https://arduino.github.io/arduino-cli/) com o core da placa instalado:

```sh
cd apps/api
uv run wiredex firmware build "Weather station" 1.2.0 \
  --url https://wiredex.example.com --email you@example.com
```

Ele pede a sua senha, que só envia por HTTPS, e encerra a sessão ao terminar.
`WIREDEX_URL` e `WIREDEX_EMAIL` substituem as duas opções. Ele compila firmware Arduino; um
build feito por outra ferramenta é zipado com um `manifest.json` e adicionado na página da
versão.

## Backups

O banco de dados é o único estado no servidor: os arquivos estão no seu bucket, e todo o
resto vem da imagem. O `deploy/backup.sh` faz o dump do banco toda noite, criptografa com
o restic e envia, mantendo cópias diárias, semanais e mensais. Como está escrito, ele mira
um bucket da Oracle Cloud e se autentica como a VM. Em outra nuvem, aponte o restic para o
seu próprio repositório: o núcleo do script, `pg_dump | restic backup --stdin`, não muda.

Use o que usar, restaure um backup antes de confiar nele. O `make restore-drill` carrega
o mais novo em um Postgres descartável na sua máquina.

## Atualizando

Traga as mudanças do upstream para o seu fork e faça o merge do PR de release. Dentro de
uma release as migrações só acrescentam ao esquema, então a versão anterior continua
funcionando enquanto a nova inicia, e um deploy que falha pode voltar atrás.

Uma release tem uma ressalva: depois da `0.5.0`, as unidades podem estar reservadas para
uma montagem ou em uso nela, o que a `0.4.x` não sabe ler. Voltar à mão para antes da
`0.5.0` exige antes cancelar ou desmontar toda montagem que segura uma unidade. Os deploys
nunca andam para trás sozinhos.

## Rodando na sua própria máquina

Para dar uma olhada sem um servidor, a stack de desenvolvimento são alguns comandos, com
os arquivos guardados em uma pasta local e sem precisar de bucket:

```bash
make install
make migrate    # inicia o Postgres no Docker e aplica as migrações
make api    # http://localhost:9000, documentação da API em /api/docs
make web    # http://localhost:5173, em outro terminal
```

Crie uma conta para ela com `cd apps/api && uv run wiredex users create --email … --name …`.
Esta configuração é para desenvolvimento: não tem TLS, e a API recarrega a cada mudança.
