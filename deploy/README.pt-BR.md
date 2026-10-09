# Deploy do Wiredex

[English](README.md) · **Português (Brasil)**

O Wiredex roda na mesma VM da OCI que o [vinilabs.cc](https://vinilabs.cc) (`corvax`,
`VM.Standard.E2.1.Micro`, menos de 1 GB de RAM). O Caddy do servidor serve o app estático
e repassa `/api/*` para o contêiner da API. O Postgres roda ao lado, no Docker. Nada
é compilado no servidor. Veja o [ADR 0009](../docs/adr/0009-single-host-deployment.md).

```
GitHub Actions (workflow Release)
  build ──► imagem da API ─► Trivy ─► ghcr.io/vinicius-cardoso/wiredex-api:<tag>
        └─► build da web (artefato)
  deploy ─► rsync para wiredex@host:/srv/wiredex ─► bin/deploy.sh <tag> ─► teste de fumaça
```

## Arquivos desta pasta

| Arquivo | Instalado como | Finalidade |
| --- | --- | --- |
| `compose.prod.yml` | `/srv/wiredex/compose.yml` | O Postgres e a API, com limites de memória e um contêiner da API endurecido |
| `wiredex.caddy` | `/etc/caddy/sites/wiredex.caddy` | O site: TLS, CSP estrita, cache, proxy de `/api/*` |
| `deploy.sh` | `/srv/wiredex/bin/deploy.sh` | Um deploy: inicia a API, espera a prontidão, troca o build da web, faz rollback em caso de falha |
| `server-setup.sh` | *(roda uma vez)* | Docker, o usuário de deploy `wiredex`, `/srv/wiredex`, o import do Caddy, o limite do journald, os backups, a reinicialização noturna da demonstração e a limpeza de arquivos |
| `backup.sh` | `/srv/wiredex/bin/backup.sh` | `pg_dump` noturno → restic → OCI Object Storage, com retenção |
| `wiredex.sh` | `/srv/wiredex/bin/wiredex` | Roda um comando da CLI `wiredex` na imagem da release no ar (contas, convites de demonstração, a reinicialização noturna da demonstração e a limpeza de arquivos) |
| `restore-drill.sh` | *(sua máquina)* | `make restore-drill`: restaura o backup mais novo em um Postgres descartável |

## Uso no dia a dia

- **Fazer o deploy de uma release:** faça o merge do PR de release. O workflow Release
  cria a tag, faz o build, a varredura e o deploy, e depois confere em
  `https://wiredex.vinilabs.cc/api/version` o commit exato.
- **Refazer o deploy ou fazer rollback:** *Actions → Release → Run workflow* com uma ref,
  por exemplo `v0.1.0`. Qualquer ref serve. Refs que não são de release saem como
  `sha-<short>`.
- **Ver o que está no ar:** `ssh corvax cat /srv/wiredex/current-tag`, ou o rodapé
  do app.
- **Histórico de deploys:** `ssh corvax tail /srv/wiredex/deploy.log`.

## Contas

Não há cadastro. As contas são criadas com a CLI `wiredex` no servidor, que
`/srv/wiredex/bin/wiredex` roda na imagem da release no ar. O `-t` dá a ela um
terminal, para o pedido de senha.

- **A sua própria conta** (uma vez, depois do primeiro deploy da v0.2):

  ```bash
  ssh -t corvax sudo -u wiredex /srv/wiredex/bin/wiredex users create --email you@example.com --name "Your name"
  ```

- **Um convidado**, em uma bancada de demonstração própria, por 7 dias por padrão
  (`--expires 12h`, `2w`, até `90d`). O comando imprime uma senha gerada uma única vez;
  envie-a junto com o e-mail:

  ```bash
  ssh corvax sudo -u wiredex /srv/wiredex/bin/wiredex demo invite --email friend@example.com --expires 7d
  ```

  O mesmo convite está no app, para uma conta que não expira: *Compartilhar uma demo* no
  menu da conta pede o e-mail, um nome e os dias, e mostra o login uma vez.

- **Recomeçar um workspace.** Exclui tudo no workspace de uma conta (peças, estoque,
  projetos, firmware, arquivos e histórico) e mantém a conta e seu login. Ele pergunta
  antes; não há como desfazer, a não ser por um backup:

  ```bash
  ssh -t corvax sudo -u wiredex /srv/wiredex/bin/wiredex workspace clear --email you@example.com
  ```

- **A reinicialização noturna da demonstração** (`wiredex-demo-reset.timer`, 03:00 no
  horário do Brasil) remove os convidados cujo acesso terminou, com suas bancadas de
  demonstração, e depois limpa os arquivos órfãos (veja
  [Armazenamento de arquivos](#armazenamento-de-arquivos)). Os módulos posteriores também
  restauram ali os dados de exemplo. Confira com
  `ssh corvax journalctl -u wiredex-demo-reset --since today`.

## Backups

Toda noite às 03:30 no horário do Brasil (06:30 UTC, em ponto), o `wiredex-backup.timer`
roda o `backup.sh` como o usuário `wiredex`:

```
pg_dump -Fc (dentro do contêiner db) ─► restic (criptografado, deduplicado)
  ─► rclone ─► bucket OCI wiredex-backups/restic   (instance principal: nenhuma chave guardada)
retenção: 7 diários, 4 semanais, 6 mensais · domingos: restic check relê 10 % dos dados
```

- **Autenticação.** A VM se autentica como ela mesma. O grupo dinâmico
  `wiredex-backup-host` casa apenas com esta instância, e a policy `wiredex-backups`
  permite que ela leia aquele bucket e gerencie seus objetos, e nada mais na conta.
- **A senha do restic** é o único segredo, em `/srv/wiredex/backup/restic-password`
  no servidor e em `~/.config/wiredex/restic-password` na máquina do dono, com uma
  terceira cópia em um gerenciador de senhas. **Sem ela os backups não podem ser
  descriptografados.**
- **Um `pg_dump` que falha faz o snapshot falhar** (`--stdin-from-command`), então um
  dump quebrado nunca substitui um bom.
- **Backups defasados geram um alerta.** O workflow *Backup check* roda todo dia às
  12:00 UTC e falha quando o backup mais novo tem mais de 26 horas, então o GitHub manda
  um e-mail ao dono. Ele usa uma chave SSH própria (o segredo do repositório
  `BACKUP_CHECK_SSH_KEY`), que o `authorized_keys` prende com `restrict` e um comando
  forçado: ela só consegue imprimir `last-success`. Não abre um shell, não roda o Docker
  nem encaminha portas.
- **Sem atraso aleatório no timer.** No systemd 249, um `daemon-reload` entre o
  horário do calendário e um atraso de `RandomizedDelaySec` empurra a execução para o dia
  seguinte. Os timers do apt recarregam o systemd em horas aleatórias, e isso pulou o
  primeiro backup agendado.
- **Confira:** `ssh corvax cat /srv/wiredex/backup/last-success` e
  `ssh corvax journalctl -u wiredex-backup --since today`. Rode um agora com
  `ssh corvax sudo systemctl start wiredex-backup`.

### Simulação de restauração

```bash
make restore-drill
```

Ela roda na sua máquina com a sua própria chave de API da OCI, então prova que os backups
são recuperáveis **sem o servidor**. Ela restaura o snapshot mais novo em um contêiner
Postgres descartável, confere-o, e falha se esse snapshot tiver mais de 36 horas.
Rode-a depois de mudar qualquer coisa nos backups, e de vez em quando de qualquer forma.

### Recuperando em um servidor novo

1. Rode o `server-setup.sh` no servidor novo (com `OCI_NAMESPACE`), e atualize a
   regra do grupo dinâmico para o OCID da nova instância.
2. Envie a senha do restic para `/srv/wiredex/backup/restic-password`.
3. Faça o deploy de qualquer versão (*Run workflow*), o que inicia um banco vazio.
4. Restaure nele:

   ```bash
   restic dump --tag postgres latest wiredex.dump |
     docker compose --file compose.yml exec -T db \
     pg_restore --username=wiredex --dbname=wiredex --clean --if-exists --exit-on-error
   ```

   O deploy do passo 3 já criou o papel `wiredex_app`, ao qual as permissões do dump
   se referem. Os papéis não fazem parte de um `pg_dump`.

5. Aponte o registro de DNS para o novo IP.

## Armazenamento de arquivos

Os anexos (datasheets, imagens, diagramas de pinagem) ficam no OCI Object Storage, fora do
disco da VM pequena. As linhas ficam no Postgres, isoladas por workspace; os bytes são
endereçados por conteúdo, por SHA-256, em `workspaces/<workspace_id>/sha256/<hex>`, então
o mesmo arquivo anexado duas vezes é guardado uma vez e dois workspaces nunca compartilham
um objeto. Veja o [design.md](../.kiro/specs/03-files-and-attachments/design.md) para o
raciocínio. A API transmite os bytes ela mesma, como `wiredex_app`; o bucket nunca é
público.

- **Cota.** Uma bancada de demonstração pode guardar 25 MB, o workspace do dono 5 GB.
  Acima da cota, um upload é recusado com 413 e diz quanto resta. O Caddy também limita um
  único upload a 26 MB na borda (`wiredex.caddy`), antes de ele chegar à API.
- **Limpeza noturna.** O `wiredex-demo-reset.service` (03:00 no horário do Brasil)
  reinicia as bancadas de demonstração e depois roda `wiredex files prune`: ele exclui os
  anexos cuja peça sumiu, as linhas de arquivo que nenhum anexo usa, e os objetos
  guardados que nenhuma linha cita. Confira com
  `ssh corvax journalctl -u wiredex-demo-reset --since today`.

### Configuração única na OCI

Feita uma vez pelo dono antes do primeiro deploy da `v0.3.0`, com aprovação explícita;
nunca a partir de uma tarefa de spec. Até estar pronta, um deploy de produção se recusa a
iniciar (de propósito), para que os uploads nunca falhem em silêncio.

1. **Bucket `wiredex-files`:** privado, camada Standard, **versionamento de objetos
   ligado**, e uma regra de ciclo de vida que **exclui as versões anteriores (não atuais)
   depois de 30 dias**. Assim, um objeto excluído ou sobrescrito pode ser recuperado por
   um mês, e depois some.
2. **Um usuário dedicado, só com este bucket.** O usuário IAM `wiredex-files` no grupo
   `wiredex-files`, com a policy `wiredex-files`:

   ```
   Allow group wiredex-files to read buckets in tenancy where target.bucket.name = 'wiredex-files'
   Allow group wiredex-files to manage objects in tenancy where target.bucket.name = 'wiredex-files'
   ```

   Nada mais na conta: a chave pode ler e escrever os objetos deste bucket e
   nada além disso.
3. **Uma Customer Secret Key** para esse usuário (Identity → o usuário → *Customer Secret
   Keys*). A OCI mostra o segredo uma vez; a chave de acesso continua visível. As duas vão
   para `/srv/wiredex/api.env`, ao lado do login do banco, e nunca saem do servidor:

   ```bash
   # Acrescentado a /srv/wiredex/api.env. Nunca versione nem copie este arquivo para fora do servidor.
   WIREDEX_FILE_STORE=s3
   WIREDEX_FILES_ENDPOINT=https://idtgsqumsw81.compat.objectstorage.us-ashburn-1.oraclecloud.com
   WIREDEX_FILES_REGION=us-ashburn-1
   WIREDEX_FILES_BUCKET=wiredex-files
   WIREDEX_FILES_ACCESS_KEY=<a chave de acesso da customer secret key>
   WIREDEX_FILES_SECRET_KEY=<o segredo, mostrado uma vez>
   ```

   Refaça o deploy (ou reinicie a API) para que ela leia as configurações.

### Recuperando um anexo excluído

Os objetos não estão no backup do restic: o backup do banco cobre as linhas, e o
versionamento do próprio bucket cobre os bytes por 30 dias. Para restaurar uma versão, no
Console da OCI abra o bucket, ligue *View Object Versions*, encontre o objeto pela chave
`workspaces/<workspace_id>/sha256/<hex>`, e baixe a versão desejada ou exclua o marcador
de exclusão mais novo, para que a versão anterior volte a ser a atual. Depois de 30
dias a regra de ciclo de vida já removeu as versões antigas, e os bytes são irrecuperáveis.

## Migrações do banco de dados

O `deploy.sh` roda `wiredex db upgrade` a partir da imagem **nova**, no contêiner
descartável `migrate`, depois que o banco está no ar e antes de a nova API iniciar. Ele
faz login como o dono do esquema, e então define a senha do papel `wiredex_app` como a que
está em `api.env`, de modo que esse arquivo é o único lugar em que ela fica guardada. As
migrações vão dentro do pacote `wiredex` (`apps/api/src/wiredex/migrations/`), então a
imagem sempre carrega as que o seu código espera.

Um deploy que falha reverte a API, mas **nunca o esquema**. Por isso, toda migração
precisa funcionar tanto com a versão nova quanto com a anterior da API:

1. **Expandir:** adicione tabelas, colunas anuláveis ou novos índices, e faça o código
   novo escrever tanto no formato antigo quanto no novo, se necessário.
2. **Contrair**, em uma release *posterior*, quando nada mais lê o formato antigo: remova
   a coluna ou a tabela antiga.

O `wiredex db downgrade <revision>` existe para o desenvolvimento local. Não faz parte
dos deploys.

## Como um deploy pode falhar, e o que acontece

| Falha | Resultado |
| --- | --- |
| O Trivy encontra uma vulnerabilidade HIGH/CRITICAL com correção disponível | Nada é publicado nem implantado |
| A nova API não responde em `/api/health/ready` dentro de 60 s | A tag anterior inicia de novo. O build da web e o `current-tag` ficam como estavam. O workflow falha, e as últimas linhas de log da API ficam na saída do job e no `deploy.log` |
| O arquivo de site do Caddy é inválido | O `caddy reload` o recusa e mantém a configuração em execução. O deploy para antes de tocar na API |
| O teste de fumaça público não vê o novo commit | O workflow falha. O servidor está servindo o que o `current-tag` diz |

## Configuração única (já feita)

Registrada para que um servidor novo possa ser configurado da mesma forma.

1. **DNS:** um registro `A` `wiredex` → o IP do servidor na Cloudflare, *DNS only* (nuvem
   cinza), para que o Caddy consiga obter o certificado.
2. **Ambiente `production` do GitHub** (deploys permitidos apenas a partir da `main`):
   - segredo `DEPLOY_SSH_KEY`: a metade privada de uma chave ed25519 dedicada, usada só pelo CI
   - segredo `DEPLOY_KNOWN_HOSTS`: a chave `ssh-ed25519` fixada do servidor
     (`ssh-keyscan -t ed25519 <ip>`, conferida com uma impressão digital confiável)
   - variáveis `DEPLOY_HOST` (o IP) e `DEPLOY_USER` (`wiredex`)
3. **O servidor:**

   ```bash
   ssh corvax "sudo DEPLOY_PUBLIC_KEY='ssh-ed25519 AAAA… wiredex-deploy' bash -s" < deploy/server-setup.sh
   ```

   Ele é idempotente, então rodá-lo de novo é seguro. Ele nunca sobrescreve os dois
   arquivos de segredos que gera, e que nunca saem do servidor:
   - `/srv/wiredex/.env`: o Postgres e o login do dono do esquema (`wiredex`), apenas
     para os serviços `db` e `migrate`
   - `/srv/wiredex/api.env`: o login da API, com o papel restrito `wiredex_app`

   Os servidores configurados antes da v0.2 tinham só o `.env`. O primeiro deploy da v0.2
   o divide sozinho (`split_database_logins` em `deploy.sh`).
4. **Backups (OCI):** o bucket `wiredex-backups` (privado, camada Standard), o grupo
   dinâmico `wiredex-backup-host` (`instance.id = '<esta VM>'`), e a policy
   `wiredex-backups`:

   ```
   Allow dynamic-group wiredex-backup-host to read buckets in tenancy where target.bucket.name = 'wiredex-backups'
   Allow dynamic-group wiredex-backup-host to manage objects in tenancy where target.bucket.name = 'wiredex-backups'
   ```

5. **GHCR:** o pacote `wiredex-api` é **público**, então o servidor baixa a imagem sem
   token. A imagem não contém segredos.

## Notas de segurança

- O usuário `wiredex` faz login apenas com a sua chave. Ele pode rodar o Docker, o que
  equivale a root neste servidor, e seu único direito de `sudo` é `systemctl reload caddy`.
- A API e o Postgres escutam apenas em loopback. O Caddy é a única entrada.
- O contêiner da API é somente leitura, não tem capabilities do Linux, não pode ganhar
  privilégios, e roda como o uid 10001.
- A API faz login no Postgres como `wiredex_app`: pode ler e escrever linhas, mas não pode
  mudar o esquema, não é superusuário, e o row-level security se aplica a ele
  ([ADR 0007](../docs/adr/0007-workspace-isolation.md)). Só o contêiner descartável
  `migrate` recebe a senha do dono.
