# Changelog

## [0.2.1](https://github.com/vinicius-cardoso/wiredex/compare/v0.2.0...v0.2.1) (2026-09-25)


### Bug Fixes

* let the web dev task notice that Vite is ready ([e68d81c](https://github.com/vinicius-cardoso/wiredex/commit/e68d81c6b3c15ff863a2c049709cf6c9b7e73028))
* open Chrome only once the API is ready too ([012bbcb](https://github.com/vinicius-cardoso/wiredex/commit/012bbcba515ff3ba0cad96635c3e2d9145eebf42))
* **web:** show an error page with a retry when a page can't load ([c4a8f24](https://github.com/vinicius-cardoso/wiredex/commit/c4a8f24c8cbc7808e3cf9c2cd5b8bb0fa45e5490))


### Documentation

* add AGENTS.md, the shared instructions for coding agents ([c221b2e](https://github.com/vinicius-cardoso/wiredex/commit/c221b2eb9c04580db3bece422c095b148726a2b4))

## [0.2.0](https://github.com/vinicius-cardoso/wiredex/compare/v0.1.1...v0.2.0) (2026-09-25)


### Features

* **api:** add a restricted wiredex_app database role ([978db52](https://github.com/vinicius-cardoso/wiredex/commit/978db52f07b6d8abda1dd9c154ef341412c68496))
* **api:** add Alembic migrations and the wiredex command line ([39f61ff](https://github.com/vinicius-cardoso/wiredex/commit/39f61ff725d561fdb3eac57b5b58fdbbc643331d))
* **api:** add endpoints to list and revoke sessions ([3acf4eb](https://github.com/vinicius-cardoso/wiredex/commit/3acf4eb35c722c44422f1cda48499bd95ee05677))
* **api:** add login, token, logout and me endpoints ([69e7542](https://github.com/vinicius-cardoso/wiredex/commit/69e75423cb8899399e90be9ce06d3bb1d8f0bad8))
* **api:** add sessions to the identity domain ([d026703](https://github.com/vinicius-cardoso/wiredex/commit/d026703042b102057e01ee3670138484b2f74f89))
* **api:** add the CreateAccount use case ([05f0472](https://github.com/vinicius-cardoso/wiredex/commit/05f0472bb7d20ca52f30cd1a7c1dfe54a0cb4918))
* **api:** add the identity domain ([9732c90](https://github.com/vinicius-cardoso/wiredex/commit/9732c90d903cb5790a302d38c0f2d68629a00a14))
* **api:** add the InviteGuest use case ([5ad8cf3](https://github.com/vinicius-cardoso/wiredex/commit/5ad8cf39a697fe214ef9f54c33a4f0d8761c8273))
* **api:** add the ListSessions and RevokeSession use cases ([b0aacfc](https://github.com/vinicius-cardoso/wiredex/commit/b0aacfc4718cc582be92b08f0281cd3cde846118))
* **api:** add the LogIn, Authenticate and LogOut use cases ([9e2ea23](https://github.com/vinicius-cardoso/wiredex/commit/9e2ea23c9ca77a23e99bcf522a3794a89f1bc06c))
* **api:** add the Password value object ([2a2f85b](https://github.com/vinicius-cardoso/wiredex/commit/2a2f85ba17152daab09fd3b4183482c8a6738286))
* **api:** add the RemoveExpiredGuests use case ([faf8b60](https://github.com/vinicius-cardoso/wiredex/commit/faf8b603a8a1a7faa524a1dad2747042682c0b45))
* **api:** add the shared kernel: clock, ids and unit of work ([f02afbe](https://github.com/vinicius-cardoso/wiredex/commit/f02afbe31dd7a138b066fff2d39e51efafdd45bd))
* **api:** add wiredex demo invite and wiredex demo reset ([d073976](https://github.com/vinicius-cardoso/wiredex/commit/d073976dae58a36cb22bbf3f7f3c5ebc7e1df73c))
* **api:** add wiredex users create ([137366e](https://github.com/vinicius-cardoso/wiredex/commit/137366e1ff29a14069b94c906c4fd2ff671dc632))
* **api:** hash passwords with Argon2id ([6bb8427](https://github.com/vinicius-cardoso/wiredex/commit/6bb8427584f080b63dd6d0517bdcc6dd617ef25d))
* **api:** isolate workspace rows with row-level security ([da1f436](https://github.com/vinicius-cardoso/wiredex/commit/da1f436b66eb90067d40ab6b3160a02236f15b88))
* **api:** issue tokens, throttle logins and equalise login timing ([c61a37c](https://github.com/vinicius-cardoso/wiredex/commit/c61a37c389172f7727099397f8fdb0f80204783c))
* **api:** log the API in as wiredex_app, and migrations as the owner ([312abf0](https://github.com/vinicius-cardoso/wiredex/commit/312abf004462bf14d4796430b51c02977f89463d))
* **api:** store sessions ([06d9f3e](https://github.com/vinicius-cardoso/wiredex/commit/06d9f3e1a7c0ef368a5d430462da018dbe9c3362))
* **api:** store users, workspaces and memberships ([a9d85a7](https://github.com/vinicius-cardoso/wiredex/commit/a9d85a793bec51590d1be8b4939c372dea31c6db))
* **deploy:** give the API its own database login ([3db80ff](https://github.com/vinicius-cardoso/wiredex/commit/3db80ffc7b26cc4d70ad62919d150717e445901d))
* **deploy:** run the wiredex CLI on the host, and the demo reset nightly ([8025607](https://github.com/vinicius-cardoso/wiredex/commit/802560736f37691defb19511809c2b9d4210dca0))
* show guests when their access ends ([6e39abe](https://github.com/vinicius-cardoso/wiredex/commit/6e39abe88c91e3f037f44b847dd0d9c32ae6eda4))
* **web:** add the CSRF header and the session hooks ([870371a](https://github.com/vinicius-cardoso/wiredex/commit/870371ad1987c2cf0135d9060d7e03330636c30a))
* **web:** add the devices page to list and log out sessions ([00d307f](https://github.com/vinicius-cardoso/wiredex/commit/00d307f2375e395faa4e8d3322e7767e0de1e9f9))
* **web:** add the login page and require login for the app ([e60fc1e](https://github.com/vinicius-cardoso/wiredex/commit/e60fc1edc31b7038dc2c471d22f49ded524fbf8b))
* **web:** show who is logged in, with a log-out button ([1ece72f](https://github.com/vinicius-cardoso/wiredex/commit/1ece72f94107215dc035be3a097baca62955a66a))


### Bug Fixes

* **api:** keep loaded objects readable after a unit of work ends ([78c90b9](https://github.com/vinicius-cardoso/wiredex/commit/78c90b9a5cde3faf8e00c4bf55c3cb47e9c912e4))
* **api:** let the identity column types use the statement cache ([cf40540](https://github.com/vinicius-cardoso/wiredex/commit/cf405400df36d483606c0677f87b0eab62418bb7))


### Documentation

* describe demo invites as built, and tick them in the roadmap ([b75a7bb](https://github.com/vinicius-cardoso/wiredex/commit/b75a7bbdacd39d4bc668d74abd9bc8abcd73d79d))
* document migrations, make coverage and the new layout ([74b8fe7](https://github.com/vinicius-cardoso/wiredex/commit/74b8fe77b7ac5e46ed2beeac874b5df971213d37))
* note that a Release-As commit must not be empty ([83a9c51](https://github.com/vinicius-cardoso/wiredex/commit/83a9c519d8b5286ddd01cf8d4bfcc85ca4cd8d20))
* record how workspace isolation is built ([1a9c9f2](https://github.com/vinicius-cardoso/wiredex/commit/1a9c9f2d04ba00ed7860faee5c2cbf1fbb4e1b53))
* tick login, logout and the devices page in the roadmap ([efe0be1](https://github.com/vinicius-cardoso/wiredex/commit/efe0be15e39b819fa9688ec42e5f1c79a4191867))


### Tests

* **api:** check revision numbering against a scratch folder ([70d001c](https://github.com/vinicius-cardoso/wiredex/commit/70d001c5e3721e3699581a55d1614e23b4acb980))
* **api:** hold the coverage floor over unit and integration tests together ([cf9e440](https://github.com/vinicius-cardoso/wiredex/commit/cf9e4406b0da0fb47e7f96727c4774cc4994693c))
* **api:** use testcontainers' community Postgres module ([48ac5b3](https://github.com/vinicius-cardoso/wiredex/commit/48ac5b34514a335610358afa01b5405a32b33817))


### Build System

* add make migrate and make migration ([4f5855e](https://github.com/vinicius-cardoso/wiredex/commit/4f5855e2a7a2adc34e40e578f7a0b88c9ca0bcba))
* **api:** add Alembic and click ([7799187](https://github.com/vinicius-cardoso/wiredex/commit/7799187f81f63905dc9f71c3b5ea60005616d053))
* **api:** add argon2-cffi ([f98d728](https://github.com/vinicius-cardoso/wiredex/commit/f98d728f8652de252823e39e952d5f4f8c3eb626))
* **api:** write migrations with plain column types, formatted by ruff ([c5040ab](https://github.com/vinicius-cardoso/wiredex/commit/c5040ab80c3575acd678897e9fb0178540cb841a))
* **deploy:** migrate the database before starting a new API ([73bb525](https://github.com/vinicius-cardoso/wiredex/commit/73bb525df48cb6b359bc66cdcd26f5df3250eb58))

## [0.1.1](https://github.com/vinicius-cardoso/wiredex/compare/v0.1.0...v0.1.1) (2026-09-24)


### Features

* **web:** use the header chip as the site icon ([65c1bbb](https://github.com/vinicius-cardoso/wiredex/commit/65c1bbbc203440465c257d6307b6c48413935064))


### Documentation

* **adr:** accept opaque sessions and CLI jobs on timers ([b90d536](https://github.com/vinicius-cardoso/wiredex/commit/b90d536c8ccdccc7d5d71d66915c01cea35e718e))
* **adr:** amend ADR 0012 with patch releases between phases ([8b8b97f](https://github.com/vinicius-cardoso/wiredex/commit/8b8b97fd218615ecf3f05dccd64b28b8926b8a47))
* close the design pass and plan demo data per module ([aafdf47](https://github.com/vinicius-cardoso/wiredex/commit/aafdf47c8d6b30bea7837c3ce37d1089895e517a))
* **deploy:** the backup runs at exactly 06:30 UTC now ([28f26d9](https://github.com/vinicius-cardoso/wiredex/commit/28f26d98d36d570e4449e2c218eed9f2e036bee4))
* tick off the logo and favicon ([eb2677e](https://github.com/vinicius-cardoso/wiredex/commit/eb2677e07c0a45ac58ad5215f57b1911c6639ac3))


### Tests

* **e2e:** check that every icon the page links to is served ([85e7009](https://github.com/vinicius-cardoso/wiredex/commit/85e70093ad58178f78d611378703495cd1087bc9))


### Continuous Integration

* ship features as patch releases until 1.0 ([04694c8](https://github.com/vinicius-cardoso/wiredex/commit/04694c806178f67b4d18409afae4042955d674fe))

## 0.1.0 (2026-09-23)


### Features

* **api-client:** add typed API client generated from OpenAPI ([73c69f9](https://github.com/vinicius-cardoso/wiredex/commit/73c69f9758baf26035225ec866d493c51c2a967c))
* **api-client:** regenerate for the readiness endpoint ([d24c3a8](https://github.com/vinicius-cardoso/wiredex/commit/d24c3a8fdc696ecb35edcfe67ab4c687466533de))
* **api:** add a command that prints the OpenAPI schema ([f4db11b](https://github.com/vinicius-cardoso/wiredex/commit/f4db11bd443f90c546846b009eea110283e7350d))
* **api:** add a readiness endpoint that checks the database ([73c56f2](https://github.com/vinicius-cardoso/wiredex/commit/73c56f29b29c759dffbb11be32db98345d589a65))
* **api:** add settings and app factory as the composition root ([625d89c](https://github.com/vinicius-cardoso/wiredex/commit/625d89c50ea48208805844ea90c2010b70384b2c))
* **api:** add system module with health and version endpoints ([a64567b](https://github.com/vinicius-cardoso/wiredex/commit/a64567b679d06f0311c7403c39495d5672188df7))
* **api:** expose the package version as wiredex.__version__ ([7cf9bf9](https://github.com/vinicius-cardoso/wiredex/commit/7cf9bf9fa3aad571dbf8711fd60ad7ba0dc499a6))
* **api:** treat empty WIREDEX_* variables as unset ([b45adc5](https://github.com/vinicius-cardoso/wiredex/commit/b45adc5168dbfc05f4ca351fdaa4217efe6dd84a))
* **i18n:** add shared EN and PT-BR catalogs ([6d09016](https://github.com/vinicius-cardoso/wiredex/commit/6d09016ffccf153bf733df3f4a3c4627d76cea29))
* **web:** add light, dark and system theme without a flash on load ([b01abca](https://github.com/vinicius-cardoso/wiredex/commit/b01abcad2ad690887b6fddcc83d93b551e5339a6))
* **web:** add OSH Purple design tokens, Tailwind v4 and self-hosted fonts ([72f9829](https://github.com/vinicius-cardoso/wiredex/commit/72f9829a3ebb086add44b2824c255a8e7eeab837))
* **web:** add the app layout, routing and an empty dashboard ([550ee26](https://github.com/vinicius-cardoso/wiredex/commit/550ee26207dbd94525f0f4a5b4ee17d71a1d67ee))
* **web:** add translations and a language switcher ([1f621b7](https://github.com/vinicius-cardoso/wiredex/commit/1f621b7828a24bcd58cc27cdf58acc279aa615ee))
* **web:** show the web and API versions in a version badge ([2f0c293](https://github.com/vinicius-cardoso/wiredex/commit/2f0c2931882262ac7e3c61c811db365680071937))


### Bug Fixes

* **api:** keep the app version out of the generated API client ([14c07cb](https://github.com/vinicius-cardoso/wiredex/commit/14c07cbdc1f73125a9b3bb8e5cb27fb9bf552968))
* **deploy:** stop the backup timer from skipping nights ([edb89cb](https://github.com/vinicius-cardoso/wiredex/commit/edb89cb7d8aeff54c642ada88e5fab8d4adf291e))
* **web:** never inline fonts as data: URIs ([d10d6a4](https://github.com/vinicius-cardoso/wiredex/commit/d10d6a4349a923d158ebb3d619e1beef988ea1c6))


### Refactoring

* **web:** load the pre-paint theme script from a file ([fc550b1](https://github.com/vinicius-cardoso/wiredex/commit/fc550b1ba1a0a80421d24ae6914d0c1bb2499806))


### Documentation

* add architecture proposal ([2172db9](https://github.com/vinicius-cardoso/wiredex/commit/2172db919d149542fa74f36cbeb1a1f944a0c4f4))
* **adr:** accept modular monolith with hexagonal modules ([c4f4a62](https://github.com/vinicius-cardoso/wiredex/commit/c4f4a623a3190742fa42bff0b9328170484f252b))
* **adr:** accept OpenAPI-generated client with openapi-fetch ([d86a578](https://github.com/vinicius-cardoso/wiredex/commit/d86a578317fd4fe09ca9645f8e84e02740049e43))
* **adr:** adopt SemVer, Conventional Commits and release-please ([743692c](https://github.com/vinicius-cardoso/wiredex/commit/743692c0d52fcffc879ee4c5e6a59694c889e99f))
* **adr:** propose architecture and platform decisions ([4c4518a](https://github.com/vinicius-cardoso/wiredex/commit/4c4518ae9465ccb158a76fac167d16c27f8a1a3d))
* **adr:** record domain modeling decisions ([bd3975f](https://github.com/vinicius-cardoso/wiredex/commit/bd3975f18dacf3d97f3617129f467c3c2c1af90a))
* **deploy:** add the deploy runbook ([64c839a](https://github.com/vinicius-cardoso/wiredex/commit/64c839acee43cbad476d90e793e292686da9ba98))
* **deploy:** document backups, the restore drill and host recovery ([73f38df](https://github.com/vinicius-cardoso/wiredex/commit/73f38df1cfcc91e319c1cff44433463b185196f5))
* **deploy:** document the backup alert and why the timer has no random delay ([747f1c9](https://github.com/vinicius-cardoso/wiredex/commit/747f1c9950d9d36abc2399e4256a4f8b830df805))
* describe router factories as the wiring mechanism ([e7774ab](https://github.com/vinicius-cardoso/wiredex/commit/e7774ab2afd874523271b46c21904eb9b18a4994))
* describe the quality gates that exist and the ones still planned ([2752b75](https://github.com/vinicius-cardoso/wiredex/commit/2752b752afae9377ac9133f12ce5de29bbe79542))
* **design:** add theme picker with ten font and palette directions ([cd483df](https://github.com/vinicius-cardoso/wiredex/commit/cd483df8ccc8e250173ca1916e44cae140b0c7e4))
* **design:** record chosen visual identity ([ee85fa4](https://github.com/vinicius-cardoso/wiredex/commit/ee85fa4c4395f5cc8d45fe817c010e3a854d0350))
* document the local database and move to PostgreSQL 18 ([9bbdf54](https://github.com/vinicius-cardoso/wiredex/commit/9bbdf542036af205f8cb9ea2bc2645a08a3d8de7))
* document toolchain versions and working make targets ([7cccdf4](https://github.com/vinicius-cardoso/wiredex/commit/7cccdf4bd1845a06c619c5e35ff23d388cc6e917))
* explain where the version lives and how to set up the release token ([a3dab4c](https://github.com/vinicius-cardoso/wiredex/commit/a3dab4cc270dfe3277e199e7c1c4ca514c07499f))
* list the architecture and api make targets ([0dbc01c](https://github.com/vinicius-cardoso/wiredex/commit/0dbc01c545fec31394676d84f5cfc3816a3ed84e))
* mark visual identity as chosen in roadmap ([f3df5a0](https://github.com/vinicius-cardoso/wiredex/commit/f3df5a0b76890c717f43f26c3f7162bd0fd3ab88))
* point to the deploy runbook and fix where the version lives ([796b5aa](https://github.com/vinicius-cardoso/wiredex/commit/796b5aaa9431b167d32bdab94a4eac922bd05f86))
* tick off releases, the production deploy and backups in the roadmap ([cbc1115](https://github.com/vinicius-cardoso/wiredex/commit/cbc1115f6aff877874c779cd392a7b497733a80d))
* tick off the app shell and version badge in the roadmap ([03a1d75](https://github.com/vinicius-cardoso/wiredex/commit/03a1d75e85457cf7b8358063671393320949c88c))
* write README with features, roadmap and project overview ([22b7efa](https://github.com/vinicius-cardoso/wiredex/commit/22b7efa7acbbd4bfb9117408a499649c31d25152))


### Tests

* **api:** cover health, version and settings behaviour ([518ecb1](https://github.com/vinicius-cardoso/wiredex/commit/518ecb185305f20fff779b6551dbb81ebd8fd344))
* **api:** run integration tests against a throwaway Postgres ([6794751](https://github.com/vinicius-cardoso/wiredex/commit/679475165aa3c21f2a68464d6e03518b42d126c2))
* **e2e:** add Playwright journeys against the real stack ([bb17395](https://github.com/vinicius-cardoso/wiredex/commit/bb17395fe4bc6813f42f7008318258cd4f78ac0d))
* enforce coverage floors for the API and web ([5b8bf1b](https://github.com/vinicius-cardoso/wiredex/commit/5b8bf1b585294ab8044767f4a9e570bc650631fb))


### Build System

* add Docker Compose Postgres 18 for local development ([76bc067](https://github.com/vinicius-cardoso/wiredex/commit/76bc067c5ff15df2a4817b350ea631aaf8cc2279))
* add make api to run the dev server with hot reload ([b34167e](https://github.com/vinicius-cardoso/wiredex/commit/b34167e1c3a189e664ab0316ab11a428833552dc))
* add make web and make client, and check TypeScript in make check ([5ce3048](https://github.com/vinicius-cardoso/wiredex/commit/5ce3048aa00a3d1009572f91b30c0ffe2bec3e74))
* add Makefile with install, lint, format, typecheck and test targets ([093fafc](https://github.com/vinicius-cardoso/wiredex/commit/093fafcc5875550c80cbe0d7a5e229b4dc1d9cc5))
* add pnpm workspace with Biome for lint and format ([f00631c](https://github.com/vinicius-cardoso/wiredex/commit/f00631cc356cf1c252192826c756212a8d77ccef))
* **api:** add FastAPI, uvicorn, pydantic-settings, httpx and import-linter ([35903ac](https://github.com/vinicius-cardoso/wiredex/commit/35903ace15e0f9348d25a4495c66120446394023))
* **api:** add SQLAlchemy (asyncio), asyncpg and testcontainers ([8a00a11](https://github.com/vinicius-cardoso/wiredex/commit/8a00a1120f9be626e7ae94edcb8eecfd2164d253))
* **api:** add the production Docker image ([0349351](https://github.com/vinicius-cardoso/wiredex/commit/0349351a97647f86be78da16c103acb1152b99e4))
* **api:** add uv project with ruff, mypy strict and pytest ([8f9d932](https://github.com/vinicius-cardoso/wiredex/commit/8f9d932b6da33dacfa7b52a435c4c57ac5f12940))
* **api:** drop ruff type-checking import rules ([17dddb2](https://github.com/vinicius-cardoso/wiredex/commit/17dddb2ccc07f6b13be8906237ba3f0677e52bc9))
* **api:** enforce module and layer boundaries with import-linter ([f2a0000](https://github.com/vinicius-cardoso/wiredex/commit/f2a0000d7ecce441065553fb25e1c100adb9027e))
* **api:** keep the version in __init__.py, out of uv.lock ([761755b](https://github.com/vinicius-cardoso/wiredex/commit/761755bf8bf83db0d1d0072fe15d8949293a9aa7))
* **api:** type-check the tests too ([969e661](https://github.com/vinicius-cardoso/wiredex/commit/969e66178c38fc8c254f1fc3bedfe80c53ab8e08))
* **deploy:** add a restore drill that runs off the server ([8dbf2f7](https://github.com/vinicius-cardoso/wiredex/commit/8dbf2f725d1ca4a18e3daa2f180efb2218ad9b4b))
* **deploy:** add the Caddy site for wiredex.vinilabs.cc ([e1cf1ac](https://github.com/vinicius-cardoso/wiredex/commit/e1cf1ac948eb86df1ae2a64b7d6cbbb9f2d23398))
* **deploy:** add the deploy script with readiness wait and rollback ([bfd93c4](https://github.com/vinicius-cardoso/wiredex/commit/bfd93c43dadf4d9272077df7932192261bb1ee64))
* **deploy:** add the idempotent one-time server setup ([2ae45a3](https://github.com/vinicius-cardoso/wiredex/commit/2ae45a362ea53e0f2588b7353c84cfd121d624bd))
* **deploy:** add the nightly database backup script ([cbf2186](https://github.com/vinicius-cardoso/wiredex/commit/cbf2186596ca3294c08edc1c42735e2bf15766cf))
* **deploy:** add the production Compose stack ([73e6bc4](https://github.com/vinicius-cardoso/wiredex/commit/73e6bc416e9cae1117f16b81f406249b55cb78ec))
* **deploy:** set up restic, rclone and the backup timer on the host ([5b167d0](https://github.com/vinicius-cardoso/wiredex/commit/5b167d0072a8d37a38e01d27c73069ca26c655af))
* let Biome parse Tailwind CSS directives ([f5f755e](https://github.com/vinicius-cardoso/wiredex/commit/f5f755e0b8a3a3eaf05eeaefb2560243fd490668))
* record that msw may not run its install script ([ad1c69a](https://github.com/vinicius-cardoso/wiredex/commit/ad1c69a3e1996f8a7547b2287a353cbaab549025))
* **web:** add Vitest, Testing Library and jsdom ([f98e2d5](https://github.com/vinicius-cardoso/wiredex/commit/f98e2d5579b9c6b3cfa0ad4ff13fe1f8f20a678a))
* **web:** scaffold Vite, React 19 and strict TypeScript app ([37c0653](https://github.com/vinicius-cardoso/wiredex/commit/37c06530121098b0398b380d1a9509390e1af1e6))


### Continuous Integration

* add quality gates for every pull request ([648a95c](https://github.com/vinicius-cardoso/wiredex/commit/648a95c350f59892979ab0cebe621cd5b77196ad))
* add release-please for versioned releases and changelog ([226c923](https://github.com/vinicius-cardoso/wiredex/commit/226c9235b59e708681fe7d5dbebbd758d65828b6))
* add weekly grouped Dependabot updates ([12e469a](https://github.com/vinicius-cardoso/wiredex/commit/12e469ab2483cf05fbddf28310b82fd6ac368fdf))
* alert when the newest backup is older than 26 hours ([a10ddf6](https://github.com/vinicius-cardoso/wiredex/commit/a10ddf6bc16e4fd88440f40e77f886c3788191d3))
* build, scan and deploy each release ([d784c0a](https://github.com/vinicius-cardoso/wiredex/commit/d784c0a234b311833552955327f8fe581b5301b0))
* keep Dependabot from bumping deliberately pinned majors ([8f8e24d](https://github.com/vinicius-cardoso/wiredex/commit/8f8e24d1a4a6c5f050ff133af73b27ea745af7ab))
* upload the backup script with every deploy ([7fef32f](https://github.com/vinicius-cardoso/wiredex/commit/7fef32f492db598297e0e15b879376e207ddfa47))
