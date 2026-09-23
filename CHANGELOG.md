# Changelog

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
