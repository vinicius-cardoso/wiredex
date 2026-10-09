# Registros de decisões de arquitetura

[English](README.md) · **Português (Brasil)**

Cada arquivo registra uma decisão: o contexto, a escolha e o que ela custa.
Os registros nunca são editados para mudar uma decisão. Um novo registro substitui o
antigo e os dois apontam um para o outro.

Os registros em si estão escritos em inglês; esta página traduz apenas o índice.

**Legenda de status:** `Accepted` significa que o dono confirmou. `Proposed` significa
que é a recomendação e aguarda a rodada de design do sistema.

| #    | Decisão                                                                  | Status   |
| ---- | ------------------------------------------------------------------------ | -------- |
| 0001 | [Monólito modular com módulos hexagonais](0001-modular-monolith.md)      | Accepted |
| 0002 | [Estoque como um livro-razão só de acréscimo, com reservas](0002-stock-ledger.md) | Accepted |
| 0003 | [Lista de materiais, fiação e firmware pertencem às revisões do projeto](0003-project-revisions.md) | Accepted |
| 0004 | [Fiação como uma netlist estruturada sobre pinagens estruturadas](0004-netlist-and-pinouts.md) | Accepted |
| 0005 | [Categorias de peças tipadas com valores de atributos em JSONB](0005-typed-part-attributes.md) | Accepted |
| 0006 | [Firmware como snapshots versionados do código-fonte e um registro de gravações por unidade](0006-firmware-snapshots.md) | Accepted |
| 0007 | [Isolamento de workspaces com RLS do Postgres e um workspace de demonstração](0007-workspace-isolation.md) | Accepted |
| 0008 | [Sessões opacas no servidor para web e mobile](0008-sessions.md)         | Accepted |
| 0009 | [Deploy com Docker em um único servidor, atrás do Caddy](0009-single-host-deployment.md) | Accepted |
| 0010 | [Cliente TypeScript gerado do OpenAPI, compartilhado por web e mobile](0010-generated-api-client.md) | Accepted |
| 0011 | [Sem broker: trabalho em segundo plano como comandos da CLI em timers](0011-no-broker.md) | Accepted |
| 0012 | [SemVer, Conventional Commits e release-please](0012-versioning-and-releases.md) | Accepted |
| 0013 | [Armazenamento de arquivos no OCI Object Storage pela API compatível com S3](0013-file-storage.md) | Accepted |
| 0014 | [Mover peças, unidades, projetos e firmware excluídos para uma lixeira](0014-soft-delete-and-trash.md) | Accepted |
| 0015 | [Registrar o histórico no Postgres com triggers](0015-history-by-triggers.md) | Accepted |
| 0016 | [Paginar listas por número, com um total](0016-page-lists-by-number.md) | Proposed |

Modelo: copie [`template.md`](template.md).
