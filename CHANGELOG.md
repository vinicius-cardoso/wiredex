# Changelog

## [0.5.0](https://github.com/vinicius-cardoso/wiredex/compare/v0.4.0...v0.5.0) (2026-09-29)


### Features

* **catalog:** describe several parts and their resolved flags in two reads ([6d684cb](https://github.com/vinicius-cardoso/wiredex/commit/6d684cb60248f80b730109b3ef2512820ae84f72))
* **catalog:** keep a part that a bill of materials names ([1dcab6c](https://github.com/vinicius-cardoso/wiredex/commit/1dcab6c6a09a5851f34b30092e13858034bb9464))
* **catalog:** mark categories not stocked, inherited along the tree ([5e2bfd6](https://github.com/vinicius-cardoso/wiredex/commit/5e2bfd6166934bdda08de783b0b7a8919808e961))
* **catalog:** set and answer the not-stocked flag over HTTP ([c303f25](https://github.com/vinicius-cardoso/wiredex/commit/c303f25b3724761a848b9e5bb9c060a7e485b15b))
* **files:** accept Gerber archives and schematics ([b055c9c](https://github.com/vinicius-cardoso/wiredex/commit/b055c9c66e028c33d37ef174713a6da908971782))
* **files:** attach photos to projects and files to revisions ([7514bec](https://github.com/vinicius-cardoso/wiredex/commit/7514bec375d53d331c65db4a4c0842cb45902a3d))
* **inventory:** answer reserved and available stock and held units ([25e8d22](https://github.com/vinicius-cardoso/wiredex/commit/25e8d22fbf91f261c9a012db574a6dd6ea674a3d))
* **inventory:** answer the available stock of several parts in one query ([20d5c87](https://github.com/vinicius-cardoso/wiredex/commit/20d5c87563d62f2a46f06555af4727ea716de1d7))
* **inventory:** apply each movement kind to its balance ([878af4e](https://github.com/vinicius-cardoso/wiredex/commit/878af4eeb076825e88d7f6cb907e765e7e9fd65e))
* **inventory:** fold what a revision holds from the ledger ([3a39204](https://github.com/vinicius-cardoso/wiredex/commit/3a392043d3172f116a12a3623462a5e4a3a0790a))
* **inventory:** hold reserved stock against recounts and moves ([e7ad160](https://github.com/vinicius-cardoso/wiredex/commit/e7ad160495ccbf4ffec3e49e1b0ce2769fc48824))
* **inventory:** keep quick-add and import from stocking consumables ([e8034e8](https://github.com/vinicius-cardoso/wiredex/commit/e8034e8b631375cda271a263e46f4bb7a75c59d7))
* **inventory:** let units be reserved for and built into revisions ([772cd79](https://github.com/vinicius-cardoso/wiredex/commit/772cd79e7c8573a98299615fc38e4b179e04e7c1))
* **inventory:** lock and sum a revision's stock in PostgreSQL ([4eeb152](https://github.com/vinicius-cardoso/wiredex/commit/4eeb15271cc3c1ed58b994656fb1add01326a59c))
* **inventory:** refuse new stock for parts that aren't stocked ([f47307f](https://github.com/vinicius-cardoso/wiredex/commit/f47307f49bed9cf43d2c7d26bae1342a3bfb05de))
* **inventory:** reserve, release, consume and return a revision's stock ([060632f](https://github.com/vinicius-cardoso/wiredex/commit/060632f84b2dd31cf484b084848c0fe3ceba2412))
* **inventory:** widen units and movements for builds ([f808a82](https://github.com/vinicius-cardoso/wiredex/commit/f808a8234468d8f68dba37d9f9c3a22ed34cdc48))
* **projects:** add the BOM tables with workspace isolation ([8ece4cc](https://github.com/vinicius-cardoso/wiredex/commit/8ece4cccbef8172c5989703e9fa07f5d0b7026f9))
* **projects:** add the project and revision values ([b2fb592](https://github.com/vinicius-cardoso/wiredex/commit/b2fb5926e9711b9923b3f96768e9334d0d329875))
* **projects:** add the projects and revisions tables with workspace isolation ([110f267](https://github.com/vinicius-cardoso/wiredex/commit/110f26710bed0b0100c4eef2d3ce0005708cdf53))
* **projects:** add, edit, remove and read BOM lines ([13a7622](https://github.com/vinicius-cardoso/wiredex/commit/13a76220c107cf4cb17e77b2ebfea35ac7a0b5f3))
* **projects:** add, fork, edit and delete revisions ([b7bb335](https://github.com/vinicius-cardoso/wiredex/commit/b7bb335df6fd1e59f53cf9764f7954e0afe7e76c))
* **projects:** choose which lots and units a reservation takes ([d946125](https://github.com/vinicius-cardoso/wiredex/commit/d94612508c49395166b3b297cd31133a5890a576))
* **projects:** compute a bill of materials' shortage report ([24800df](https://github.com/vinicius-cardoso/wiredex/commit/24800df5540547f9c129e938e39396420dc29485))
* **projects:** copy a revision's bill of materials when it is forked ([28ab4b8](https://github.com/vinicius-cardoso/wiredex/commit/28ab4b88139d13864fa140ce084bce0e36d2d8ec))
* **projects:** create, edit, list and delete projects ([7e4b27b](https://github.com/vinicius-cardoso/wiredex/commit/7e4b27bf1e3016ca487ea3d69253f54473da126f))
* **projects:** expose bills of materials over HTTP ([b3b6adf](https://github.com/vinicius-cardoso/wiredex/commit/b3b6adfe66b5434fb81277ffe048c51333ae5ab6))
* **projects:** expose projects and revisions over HTTP ([64d93c0](https://github.com/vinicius-cardoso/wiredex/commit/64d93c09048aff7a0ad894ce300e497b9577f1c5))
* **projects:** expose the build lifecycle over HTTP ([7b4dd48](https://github.com/vinicius-cardoso/wiredex/commit/7b4dd48cf5ea2bc5085bd828a59f7a5f2fdeeddd))
* **projects:** model BOM lines and a revision's bill of materials ([d48d51b](https://github.com/vinicius-cardoso/wiredex/commit/d48d51b6050aaeee9f201ee864aac4d587d474d7))
* **projects:** model projects, revisions and a project's revisions ([db7af92](https://github.com/vinicius-cardoso/wiredex/commit/db7af9274fa0667214b1dc53cbe4d405c87e7c95))
* **projects:** model the build lifecycle as a table ([bc07641](https://github.com/vinicius-cardoso/wiredex/commit/bc07641a701f785424e2ed0060bd8e23b81ec773))
* **projects:** open the module and its import contracts ([eb28a74](https://github.com/vinicius-cardoso/wiredex/commit/eb28a74fa8ec2d9673e641a5995c33f5518287d2))
* **projects:** read and write designator lists ([3729459](https://github.com/vinicius-cardoso/wiredex/commit/37294595905a6d9b2f280e4cade3a99f80ef1b06))
* **projects:** reserve, cancel, build and dismantle revisions ([e9394f3](https://github.com/vinicius-cardoso/wiredex/commit/e9394f3982f636d3bbf44ca02e5ef7a75b588c9a))
* **projects:** run a transition in one transaction across three modules ([cd20b42](https://github.com/vinicius-cardoso/wiredex/commit/cd20b429222442fd66cff034cc24a58726b7485a))
* **projects:** seed the demo bench with a reserved build ([656d7f2](https://github.com/vinicius-cardoso/wiredex/commit/656d7f2b7cd0e51d5d90a4e0de57ee6ec95f3adc))
* **projects:** seed the demo workspace with sample bills of materials ([aebc522](https://github.com/vinicius-cardoso/wiredex/commit/aebc52239daa09b3c3c66580bbe8affdf9f94c3d))
* **projects:** seed the demo workspace with sample projects ([bf2a3b5](https://github.com/vinicius-cardoso/wiredex/commit/bf2a3b5aedb189539a4bec1f3e556ee1de7cd6fa))
* **projects:** store BOM lines and designators in PostgreSQL ([c737194](https://github.com/vinicius-cardoso/wiredex/commit/c7371945748fd42ee771388a69fb05f0466aa2ac))
* **projects:** store projects and revisions in PostgreSQL ([6672567](https://github.com/vinicius-cardoso/wiredex/commit/6672567c3ab0896d3c564e176551e2799ec8e711))
* **web:** add photos to projects and files to revisions ([c3af5bd](https://github.com/vinicius-cardoso/wiredex/commit/c3af5bdf783d480405dd80926190081c4e63f5cd))
* **web:** browse and create projects ([7aa7535](https://github.com/vinicius-cardoso/wiredex/commit/7aa7535f608c97b87fdf48786822a67d3437d674))
* **web:** edit projects and add, fork, edit and delete revisions ([3685921](https://github.com/vinicius-cardoso/wiredex/commit/368592128df0c11a63ad7b98b40bc87df62f1cb6))
* **web:** mark categories not stocked and show consumables as such ([47180d9](https://github.com/vinicius-cardoso/wiredex/commit/47180d91a97f8c1914dbff7132b8050017b05aa0))
* **web:** reserve, build, cancel and dismantle from the revision panel ([121c551](https://github.com/vinicius-cardoso/wiredex/commit/121c55192689b3d36a92906b8bdd74b1e3223c6c))
* **web:** show a revision's bill of materials and its shortages ([9b36fc7](https://github.com/vinicius-cardoso/wiredex/commit/9b36fc762f76a1e741234c77b43fb8e5165c8598))
* **web:** show reserved and available stock and who holds it ([5a9992f](https://github.com/vinicius-cardoso/wiredex/commit/5a9992f245d2b41dba2e4c48e4a729aa49b5e15e))
* **web:** show units reserved for and in use in revisions ([5480065](https://github.com/vinicius-cardoso/wiredex/commit/5480065fcbeafd8354b6a2150827b061943f537f))
* **web:** show what a build holds ([7a6034b](https://github.com/vinicius-cardoso/wiredex/commit/7a6034bec12fac7cd67f5af7f3faaa667a43f8dc))
* **web:** write a bill of materials from the keyboard ([cd7c210](https://github.com/vinicius-cardoso/wiredex/commit/cd7c21049d84dd8ec0d0a3ee6ed4fd400a2b9704))


### Performance

* **inventory:** count every location's lots in one query ([4fd1357](https://github.com/vinicius-cardoso/wiredex/commit/4fd13572b919efe7f36eee815b0e77abee7189f8))


### Documentation

* add the bill-of-materials spec ([4e2341c](https://github.com/vinicius-cardoso/wiredex/commit/4e2341c6425c5d2e7ea6ffc590ae7d71b9076c24))
* close the projects phase ([2ae5de5](https://github.com/vinicius-cardoso/wiredex/commit/2ae5de507cfb88ba4f6e6fdf7e80f86e1922b3a0))


### Tests

* **e2e:** cover projects, revisions, forking, tags and files ([bb17217](https://github.com/vinicius-cardoso/wiredex/commit/bb17217e6420c6ebc0928537c3c16e15d0349a61))
* **e2e:** cover the bill of materials, its shortages and consumables ([bc743eb](https://github.com/vinicius-cardoso/wiredex/commit/bc743ebe1021dc3484737df815403db53e048dd2))
* **e2e:** cover the build lifecycle journey ([ef7c769](https://github.com/vinicius-cardoso/wiredex/commit/ef7c769ab9c01437f19c16e20720cb343380c527))

## [0.4.0](https://github.com/vinicius-cardoso/wiredex/compare/v0.3.0...v0.4.0) (2026-09-28)


### Features

* **catalog:** check every attribute of a draft and find categories by path ([64a33af](https://github.com/vinicius-cardoso/wiredex/commit/64a33afd738007fb7d831d4a9f77572dd0df8181))
* **catalog:** mark categories as tracked individually ([8ed13c7](https://github.com/vinicius-cardoso/wiredex/commit/8ed13c727fd1852e9543be7d798fe9c991f4d3a8))
* **catalog:** review and define part drafts inside a caller's transaction ([c75ac85](https://github.com/vinicius-cardoso/wiredex/commit/c75ac857faddef94e4e8b4f8090990eb350b208c))
* **inventory:** add the inventory tables with workspace isolation ([4982c43](https://github.com/vinicius-cardoso/wiredex/commit/4982c438f38d2145116a8c90eaccaf5603c25baf))
* **inventory:** add the inventory value objects ([2468173](https://github.com/vinicius-cardoso/wiredex/commit/2468173d98df751d176ce176b5476e85136d6974))
* **inventory:** add the location tree entity ([9445c89](https://github.com/vinicius-cardoso/wiredex/commit/9445c892cf04e13b928483f0c85a5e012f3e7b1e))
* **inventory:** add the tracked unit entity ([06d2ade](https://github.com/vinicius-cardoso/wiredex/commit/06d2ade3b799096898d6ebfd745c9d14cb2e6926))
* **inventory:** add the units table with workspace isolation ([4df7c4a](https://github.com/vinicius-cardoso/wiredex/commit/4df7c4af0c881eba1b99901f8c1f496a4bef5ef5))
* **inventory:** add unit identity value objects ([d5d3bf7](https://github.com/vinicius-cardoso/wiredex/commit/d5d3bf770e8b20a34607bc0d22556b89dc2e1b30))
* **inventory:** declare the inventory ports ([726f521](https://github.com/vinicius-cardoso/wiredex/commit/726f521b96b8f1b4ed2253f0197a9db488df110c))
* **inventory:** declare the units port ([c44283a](https://github.com/vinicius-cardoso/wiredex/commit/c44283ac2751da360d8059913704d1cc33d566e0))
* **inventory:** expose inventory over HTTP ([83f4c35](https://github.com/vinicius-cardoso/wiredex/commit/83f4c35996936b9de6e7fe12131f2b9ca5d7450f))
* **inventory:** expose quick-add and sheet import over HTTP ([d7a629a](https://github.com/vinicius-cardoso/wiredex/commit/d7a629a5e037cfdc96b5e22107af7a1de531b183))
* **inventory:** expose units over HTTP ([68787f2](https://github.com/vinicius-cardoso/wiredex/commit/68787f2ff640fed6e9c804967e585d44149bb5b4))
* **inventory:** list and search units ([73f125f](https://github.com/vinicius-cardoso/wiredex/commit/73f125fad24953d9b6dc3ae83e91b9ba80de25f3))
* **inventory:** manage the location tree ([76e0cbd](https://github.com/vinicius-cardoso/wiredex/commit/76e0cbd7fecbac07c9e414168f7ff0509a9ef2f6))
* **inventory:** model the stock ledger and balance projection ([05beed3](https://github.com/vinicius-cardoso/wiredex/commit/05beed3633e5f83d3138de381d03cd65f023565f))
* **inventory:** open the module and its import contracts ([c268125](https://github.com/vinicius-cardoso/wiredex/commit/c2681250d045f14f7de54c1096a176b88a8b946a))
* **inventory:** plan an import row's stock and fingerprint the plan ([eaf9608](https://github.com/vinicius-cardoso/wiredex/commit/eaf96081b3af084a34a8d13293c32af2b40a6112))
* **inventory:** preview and import a sheet in one transaction ([da877fa](https://github.com/vinicius-cardoso/wiredex/commit/da877fa5fc4473ce82f59565061e9b48bb40f87b))
* **inventory:** quick-add a part with its first stock ([a08c042](https://github.com/vinicius-cardoso/wiredex/commit/a08c042fe7715ab0b1df1d31f2f8ee9fc7030a95))
* **inventory:** read and write import sheets ([753d2bc](https://github.com/vinicius-cardoso/wiredex/commit/753d2bcac5874318f7935805e73b66b1fc078886))
* **inventory:** rebuild stock balances from the CLI ([30b95a4](https://github.com/vinicius-cardoso/wiredex/commit/30b95a4aab608288f619a58d6b1c85b9626cc8d3))
* **inventory:** receive tracked units ([f3c8eb0](https://github.com/vinicius-cardoso/wiredex/commit/f3c8eb02456b98a24ec7d0eb4ba3a21e2ec01bc0))
* **inventory:** receive, adjust and move stock ([d2ecd4e](https://github.com/vinicius-cardoso/wiredex/commit/d2ecd4efaa274797dbe61bdc730a9cd49953577f))
* **inventory:** relabel, retire, move and delete units ([d788023](https://github.com/vinicius-cardoso/wiredex/commit/d788023acea92660d09a933bc81b71e7e7f4945f))
* **inventory:** run quick-add and import in one transaction with the catalog ([d326a95](https://github.com/vinicius-cardoso/wiredex/commit/d326a95d642b8f31baf4e131ac36e0264c94605f))
* **inventory:** seed the demo workspace with sample stock ([80c0e4e](https://github.com/vinicius-cardoso/wiredex/commit/80c0e4e0e9b5ac3887bc25873b3a4b3935061aa8))
* **inventory:** seed the demo workspace with sample units ([44b4bff](https://github.com/vinicius-cardoso/wiredex/commit/44b4bff689d834b121c13615bda5c0a05cce70de))
* **inventory:** store inventory in PostgreSQL ([6558a10](https://github.com/vinicius-cardoso/wiredex/commit/6558a10aadcb86fdfa30a43d65bd22a0b40cf72e))
* **inventory:** store units in PostgreSQL ([c6ebad0](https://github.com/vinicius-cardoso/wiredex/commit/c6ebad0c0257ba6a7ac997aea8185d48d4c77f2d))
* **inventory:** total stock per part and rebuild balances from the ledger ([5f440cc](https://github.com/vinicius-cardoso/wiredex/commit/5f440cc4978fd4811ecf8af870acab405d407b37))
* **web:** duplicate a part from its page ([65c886e](https://github.com/vinicius-cardoso/wiredex/commit/65c886ed46f714ad3ff8733271c28b6c837001d1))
* **web:** find locations by name or short code ([7ac4f86](https://github.com/vinicius-cardoso/wiredex/commit/7ac4f867da748800d70391c44c2dfabd578cc398))
* **web:** import parts and stock from a sheet ([02eec97](https://github.com/vinicius-cardoso/wiredex/commit/02eec97592df4afde7d19f127eaadc1b2f03cf36))
* **web:** manage storage locations ([2b49f63](https://github.com/vinicius-cardoso/wiredex/commit/2b49f63098e8ca5d9503523b5a62b50af0fbb9b5))
* **web:** quick-add a part from any page ([60ebc2b](https://github.com/vinicius-cardoso/wiredex/commit/60ebc2b6f4e92f9da0ae293c85d8c868b7c34b03))
* **web:** receive, list and manage tracked units ([9e44946](https://github.com/vinicius-cardoso/wiredex/commit/9e44946ef254e7b43d8e94fe7f4c63edc0a74659))
* **web:** show and change stock per part ([089eb4d](https://github.com/vinicius-cardoso/wiredex/commit/089eb4dd0adfd902bc2b103a3e175554079ae3f9))


### Bug Fixes

* **inventory:** cap a unit receipt at a hundred units ([b506cea](https://github.com/vinicius-cardoso/wiredex/commit/b506ceadd5cabe8ec196343a63a4f56e97e2be74))
* **inventory:** lock a lot's balance while a movement is recorded ([9a78bbb](https://github.com/vinicius-cardoso/wiredex/commit/9a78bbb1dae02fc75434d62d20bea66fa09ea1a1))
* **inventory:** lock a unit while it is retired or moved ([f3cd174](https://github.com/vinicius-cardoso/wiredex/commit/f3cd174732f89a20db32e06d28aaf2cc1068ed84))
* **inventory:** make the stock ledger append-only in the database ([72328bc](https://github.com/vinicius-cardoso/wiredex/commit/72328bc6848478ee22bfce3378d8760d7650e164))
* **inventory:** refuse a loose move of a unit-tracked part ([133ec96](https://github.com/vinicius-cardoso/wiredex/commit/133ec96ffe4b6ab71d43aee21e1518c0422884d8))
* **web:** hide the loose adjust and move for a unit-tracked part ([03f823b](https://github.com/vinicius-cardoso/wiredex/commit/03f823b59cbfcb6afa9178737b2d45b4fc341af5))
* **web:** refetch a list whose first load raced a write ([44fbb75](https://github.com/vinicius-cardoso/wiredex/commit/44fbb75d964aca0da0185e37d0d228c83403c70a))


### Refactoring

* **files:** type the enum lookups with their own class ([17d69e3](https://github.com/vinicius-cardoso/wiredex/commit/17d69e3447c0974e06bf311aab32173691020198))
* **inventory:** let receipts run inside a transaction another use case opened ([7d50580](https://github.com/vinicius-cardoso/wiredex/commit/7d505807d9e29d8e43f00ae0207315bae516372f))


### Documentation

* add the inventory-stock spec for v0.4 ([3cf65ad](https://github.com/vinicius-cardoso/wiredex/commit/3cf65adbefb6696b9503145debac001877b700da))
* add the tracked-units requirements and design ([2dd9f72](https://github.com/vinicius-cardoso/wiredex/commit/2dd9f72d681730a81e80886d2da8b35dbcf27cc8))
* close the inventory phase ([b6e1c9b](https://github.com/vinicius-cardoso/wiredex/commit/b6e1c9b4114838c4968d8895c19f98afe387fcac))
* **inventory:** record the ledger implementation and short codes ([e3bc6f5](https://github.com/vinicius-cardoso/wiredex/commit/e3bc6f51484a062200bdc7f98aaccbb5c506c95a))
* number the specs in build order ([9a252df](https://github.com/vinicius-cardoso/wiredex/commit/9a252df8552650e0eb18ffbe389152ce42f079e6))
* plan history for everything in v0.8 ([6cf134f](https://github.com/vinicius-cardoso/wiredex/commit/6cf134f4a79d84f486c6b29eadd5a44f39376288))


### Tests

* **e2e:** cover quick-add, duplicate and sheet import ([e055923](https://github.com/vinicius-cardoso/wiredex/commit/e055923446ed92d92dee80277ae3b33b81b1b8f7))
* **e2e:** cover the inventory journey ([52a0d82](https://github.com/vinicius-cardoso/wiredex/commit/52a0d82636a0a0e68b61e854b9173bef04133862))
* **e2e:** cover the tracked-units journey ([3900a05](https://github.com/vinicius-cardoso/wiredex/commit/3900a059e2991c88fbab5831dbc2f6a0cd8c954d))
* **e2e:** drop the unused unit codes in the units journey ([57478f7](https://github.com/vinicius-cardoso/wiredex/commit/57478f75f18eb28fa2bd5b9ddcacb7b848c78310))

## [0.3.0](https://github.com/vinicius-cardoso/wiredex/compare/v0.2.1...v0.3.0) (2026-09-26)


### Features

* **api:** keep JSONB numbers exact with Decimal ([a359ff8](https://github.com/vinicius-cardoso/wiredex/commit/a359ff85c9ab202cd03ff4a06161c270965e1fbe))
* **catalog:** add sample pinouts to the demo bench ([919c9a7](https://github.com/vinicius-cardoso/wiredex/commit/919c9a71f147d27e9d281a60a9c48f66a372da84))
* **catalog:** add the catalog tables with workspace isolation ([a377d1c](https://github.com/vinicius-cardoso/wiredex/commit/a377d1cdd217f814620682a29cacc2c6b3c6fe9e))
* **catalog:** add the catalog value objects ([e9a1926](https://github.com/vinicius-cardoso/wiredex/commit/e9a1926b911597816b647307e322c553fe034104))
* **catalog:** add the category and part definition entities ([756c50c](https://github.com/vinicius-cardoso/wiredex/commit/756c50ca6ab98c741ff4b4795e65535f46fced8a))
* **catalog:** add the pin value objects ([9dfb574](https://github.com/vinicius-cardoso/wiredex/commit/9dfb574bd3900be20605c06440be1855bbfa3d3a))
* **catalog:** add the pins table, tied to its part's workspace ([5d948b4](https://github.com/vinicius-cardoso/wiredex/commit/5d948b40f17fa0f392195501553935a92ca51a1d))
* **catalog:** collect pins into a pinout that names the row it refuses ([6545e67](https://github.com/vinicius-cardoso/wiredex/commit/6545e6770bb523bc72dae869cb73575480ee02c5))
* **catalog:** compile part searches to SQL ([fc1b8b2](https://github.com/vinicius-cardoso/wiredex/commit/fc1b8b236649fa1095d76a6976773d98d3e1150a))
* **catalog:** count facets in PostgreSQL ([8cb9035](https://github.com/vinicius-cardoso/wiredex/commit/8cb90358a08ee4bbc52997cf23f5903557729d81))
* **catalog:** declare the catalog ports ([f346057](https://github.com/vinicius-cardoso/wiredex/commit/f34605702e1457507ff87b27bcc9fac9771ad340))
* **catalog:** define and revise part definitions ([f9469bf](https://github.com/vinicius-cardoso/wiredex/commit/f9469bf9f3dee326104b650fd250dba264b337d0))
* **catalog:** define attributes on a category ([b1be13f](https://github.com/vinicius-cardoso/wiredex/commit/b1be13f6e78a3fe35d029ff4f6c94445d533ebfd))
* **catalog:** describe part searches as composable filters ([6ee834b](https://github.com/vinicius-cardoso/wiredex/commit/6ee834b632f71b6e265b9095d51d2a2201102667))
* **catalog:** expose part search and facets over HTTP ([c690493](https://github.com/vinicius-cardoso/wiredex/commit/c69049342065083d87102338a8ceac527ba91654))
* **catalog:** expose pinouts over HTTP ([537614b](https://github.com/vinicius-cardoso/wiredex/commit/537614b2bfafd421a51497499a63d5abb7c9e86e))
* **catalog:** expose the catalog over HTTP ([957bfdd](https://github.com/vinicius-cardoso/wiredex/commit/957bfddda89d464b41c9cf3a0f402b3d92c33850))
* **catalog:** find a category's descendants in one query ([261804c](https://github.com/vinicius-cardoso/wiredex/commit/261804cdf36699fd8363ef696cf1e43e34726048))
* **catalog:** index part names and numbers for text search ([7664644](https://github.com/vinicius-cardoso/wiredex/commit/766464427dc87564b9ea761d92828e550faa98fa))
* **catalog:** manage the category tree ([a6b14c8](https://github.com/vinicius-cardoso/wiredex/commit/a6b14c88a482e5a425817fe050e0b06d5c0d2869))
* **catalog:** open the module and its import contracts ([d4ab6b6](https://github.com/vinicius-cardoso/wiredex/commit/d4ab6b6f5b77b8ede17520e056bd754f85df4dcb))
* **catalog:** parse and format engineering notation ([3e74107](https://github.com/vinicius-cardoso/wiredex/commit/3e74107debd7eb22ed55e1a5002acfe5cc74ce4e))
* **catalog:** read and replace a part's pinout ([287ed02](https://github.com/vinicius-cardoso/wiredex/commit/287ed0261edb33fc82f58d47876f3f4b63f7ee40))
* **catalog:** resolve attribute schemas along the category chain ([fb1719f](https://github.com/vinicius-cardoso/wiredex/commit/fb1719f29178d682bc788639c55ffaf3551157ad))
* **catalog:** search parts and count facets against the category schema ([90b2f03](https://github.com/vinicius-cardoso/wiredex/commit/90b2f03f00fd9b3f6576004ffefd9291f5f24223))
* **catalog:** seed the demo workspace with sample parts ([910c11e](https://github.com/vinicius-cardoso/wiredex/commit/910c11e580f62188d3bd9738041a586b758fbf13))
* **catalog:** sort searches and continue them with an opaque cursor ([ac5e225](https://github.com/vinicius-cardoso/wiredex/commit/ac5e225ce3d689b84f2c45b59bd78c7b89df1272))
* **catalog:** store pinouts in PostgreSQL ([5c76db1](https://github.com/vinicius-cardoso/wiredex/commit/5c76db16f6a51e75bd1750d5b8cd277af852b76e))
* **catalog:** store the catalog in PostgreSQL ([46e722c](https://github.com/vinicius-cardoso/wiredex/commit/46e722cc77f7b4f4ec8ff5159aa5199fdb09e100))
* **catalog:** validate attribute values by kind ([0cf4be0](https://github.com/vinicius-cardoso/wiredex/commit/0cf4be0c480948ec5b63330c17f983bc2d0bdc2c))
* **deploy:** limit uploads at the edge and prune files nightly ([d98025b](https://github.com/vinicius-cardoso/wiredex/commit/d98025bba9c1116757d82d9fb64080f2114db217))
* **files:** add the files and attachments tables ([de004b4](https://github.com/vinicius-cardoso/wiredex/commit/de004b4828d86eb89b30f1458f43e956588c9d2c))
* **files:** attach, list, open, change and remove attachments ([678f307](https://github.com/vinicius-cardoso/wiredex/commit/678f30747a689cd81a90919cd7c082f47e7b4f26))
* **files:** configure and wire the file store ([6f395c8](https://github.com/vinicius-cardoso/wiredex/commit/6f395c8d18bba93be9e2c1690cbfa2891a4a3101))
* **files:** expose attachments over HTTP ([9ce1cb2](https://github.com/vinicius-cardoso/wiredex/commit/9ce1cb2f4d23bebbea1d857fa65b6e00821db139))
* **files:** open the files module and its values ([70fb156](https://github.com/vinicius-cardoso/wiredex/commit/70fb156c36ab902da46e4e21e9d4aeaac5a19d46))
* **files:** prune orphaned files nightly and clear demo uploads ([e55f791](https://github.com/vinicius-cardoso/wiredex/commit/e55f7915b7bc286db465fa250c8753cf61211c7d))
* **files:** sniff file types and add the file and attachment entities ([6ad0a5c](https://github.com/vinicius-cardoso/wiredex/commit/6ad0a5ce259f397be55b47760f3dd48a326b0893))
* **files:** store files and attachments in PostgreSQL ([1f163d6](https://github.com/vinicius-cardoso/wiredex/commit/1f163d6df4bbb03c23f8f0fd8fcddc0d4951c96f))
* **files:** store files in a local folder for development ([90cee3b](https://github.com/vinicius-cardoso/wiredex/commit/90cee3bb9d33ea492c6586b0e72c5a62a7dfbcdd))
* **files:** store files through the S3-compatible API ([6da243d](https://github.com/vinicius-cardoso/wiredex/commit/6da243d2c2e2ed167b575f22b62197370d50961c))
* **identity:** put the caller's workspace on the authenticated user ([a2893ab](https://github.com/vinicius-cardoso/wiredex/commit/a2893ab64f62b4efc573cafc092d10eabcc05db0))
* **web:** add and edit parts with schema-driven fields ([06510e4](https://github.com/vinicius-cardoso/wiredex/commit/06510e41621d90f7921b976b1a3b310cda9dda4c))
* **web:** browse the part catalog ([161c070](https://github.com/vinicius-cardoso/wiredex/commit/161c070d319635b25e6c772fb6fa64d5c04287c7))
* **web:** edit and paste a part's pinout ([bb99fac](https://github.com/vinicius-cardoso/wiredex/commit/bb99face546f3bfb73a15c2176d6f5d422a525f2))
* **web:** keep part searches in the address ([05067ed](https://github.com/vinicius-cardoso/wiredex/commit/05067edc592a07eef66341d3cb75180c5e655f36))
* **web:** manage categories and flag parts needing review ([1185bb4](https://github.com/vinicius-cardoso/wiredex/commit/1185bb4865a99f3ab94d217ee00602c00642daa3))
* **web:** read a pin table pasted from a spreadsheet or datasheet ([fde6192](https://github.com/vinicius-cardoso/wiredex/commit/fde619254ef8b7fa1769ddcf422a2a7192c4e210))
* **web:** search parts by attributes, pins and text ([5754489](https://github.com/vinicius-cardoso/wiredex/commit/57544892bb67c1c2d51d01674df0c640763a675c))
* **web:** show a part's attachments ([950b314](https://github.com/vinicius-cardoso/wiredex/commit/950b3142e4df91efa6bb5e34707c02a4bb08805a))
* **web:** show a part's pinout ([713c4f8](https://github.com/vinicius-cardoso/wiredex/commit/713c4f8363eeb92c30f524526b64d48aa63a1047))
* **web:** upload attachments by dropping or picking a file ([504c6f0](https://github.com/vinicius-cardoso/wiredex/commit/504c6f0c793d19fc17f0f23aa8edd184e892f121))


### Bug Fixes

* **catalog:** give a new guest's bench its sample catalog at once ([e53973e](https://github.com/vinicius-cardoso/wiredex/commit/e53973ea0f0076010c990d059f3d9ff5d5a50cd9))
* **catalog:** read look-alike micro and ohm symbols the same ([6f5ff81](https://github.com/vinicius-cardoso/wiredex/commit/6f5ff81dc2f15c0192170a394566ff43c4368c87))
* **deploy:** let a full 25 MiB upload through Caddy ([bf8f75a](https://github.com/vinicius-cardoso/wiredex/commit/bf8f75a89a5aa248f4487273f2c4e12138c4c2a9))
* **files:** keep local uploads in apps/api/.files wherever the API starts ([66470fe](https://github.com/vinicius-cardoso/wiredex/commit/66470fe8b8669aa25ddfd70ce9d37250b3540d7e))
* **files:** keep uploads in flight safe from the nightly prune ([783d58e](https://github.com/vinicius-cardoso/wiredex/commit/783d58ec458bf574ac67e93eded265b5f80b7fe9))
* **files:** let queries see an attachment removed in the same transaction ([200b8c1](https://github.com/vinicius-cardoso/wiredex/commit/200b8c1dec17d926a1c6f8a4a8e5fb021ca00efd))
* **files:** repair lost objects on upload and fail downloads cleanly ([c19d29b](https://github.com/vinicius-cardoso/wiredex/commit/c19d29b802785683d0734e9983c4014242f33a9b))
* **web:** ask before navigating away from unsaved pinout edits ([150af94](https://github.com/vinicius-cardoso/wiredex/commit/150af9412623c9525fc56597fa3a335d37b2ed76))
* **web:** keep the attachment rows readable ([1c6032b](https://github.com/vinicius-cardoso/wiredex/commit/1c6032baf0f2218cb9710059261304a57fb85765))
* **web:** keep the pinout editor readable on a phone ([9423c85](https://github.com/vinicius-cardoso/wiredex/commit/9423c85471230f093cdc0cfa0d4b4d4eb9ed885c))
* **web:** keep the search filters inside their panel ([a115595](https://github.com/vinicius-cardoso/wiredex/commit/a115595385976af3d24112af154ed308f94e4bc2))
* **web:** word the required-field message plainly ([ba52b94](https://github.com/vinicius-cardoso/wiredex/commit/ba52b94b3a7e9e6cf9287c137d46e16d3da17bc4))


### Documentation

* add the catalog-foundation spec for v0.3 ([4fcb60a](https://github.com/vinicius-cardoso/wiredex/commit/4fcb60aa2d1e4f2b03b634b27943977677e7da8a))
* add the files-and-attachments spec for v0.3 ([6cdc046](https://github.com/vinicius-cardoso/wiredex/commit/6cdc0464d5a70f2e1450d18033a0c6831a481d20))
* add the parametric-search spec for v0.3 ([cc0a7a5](https://github.com/vinicius-cardoso/wiredex/commit/cc0a7a51c294c5a8b042b68a038ce28a5f82d553))
* add the part-pinouts spec for v0.3 ([568a28f](https://github.com/vinicius-cardoso/wiredex/commit/568a28f151eef786c6c20af7d3e318088d42fea0))
* make the spec's MPN check ignore case in the manufacturer too ([35969ff](https://github.com/vinicius-cardoso/wiredex/commit/35969ff66225f02f561e2670393960592b25c2cb))
* record how files are stored ([45d2e27](https://github.com/vinicius-cardoso/wiredex/commit/45d2e27a475bba3fa198a37dda79573707404d0d))
* record how pinouts are built ([f684c1c](https://github.com/vinicius-cardoso/wiredex/commit/f684c1cfa77e33c7802b7941200428d90145007c))
* record how search works and close v0.3.0 ([851796b](https://github.com/vinicius-cardoso/wiredex/commit/851796b71517fe379b7dca1a9aa4c83216620f3d))
* shape the part-pinouts spec the way Kiro expects ([6d9c30b](https://github.com/vinicius-cardoso/wiredex/commit/6d9c30b7d5cdd9e3b803db4ccbe34177fb63523d))
* ship each spec as its own PR ([e983f2e](https://github.com/vinicius-cardoso/wiredex/commit/e983f2e25809e6819937ece9357bcdab0aaec1aa))
* tick task 2 and add a dependency graph to the catalog spec ([027210f](https://github.com/vinicius-cardoso/wiredex/commit/027210fa245366ec97b62a3caf921f165639458a))
* tick tasks 3 to 20 of the catalog spec ([1a67ccf](https://github.com/vinicius-cardoso/wiredex/commit/1a67ccfc6006e5d9afbdec3ce086971b708d4cfc))


### Tests

* **catalog:** prove the catalog routes need a session and the CSRF header ([6ae4df9](https://github.com/vinicius-cardoso/wiredex/commit/6ae4df988cefd19e2f0e46604c1c9933ac476adf))
* **e2e:** cover parametric search ([dd8769d](https://github.com/vinicius-cardoso/wiredex/commit/dd8769d76eaba4f103ae4dc51a47f79b476789e6))
* **e2e:** cover pasting and saving a pinout ([e99210f](https://github.com/vinicius-cardoso/wiredex/commit/e99210f51fcf3afa281053b47f8f83e68519edd0))
* **e2e:** cover the catalog journey ([88b7b23](https://github.com/vinicius-cardoso/wiredex/commit/88b7b2381f8ce8367084f2062c8c76fe392442e6))
* **e2e:** cover uploading, opening and removing attachments ([0947880](https://github.com/vinicius-cardoso/wiredex/commit/0947880cba32653191da75749f70949b8fb417c9))

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
