# Changelog

## [1.4.0](https://github.com/kanjieater/OmniSave/compare/v1.3.1...v1.4.0) (2026-07-03)


### Features

* add platform-agnostic activity event ingestion ([1dba36c](https://github.com/kanjieater/OmniSave/commit/1dba36c90f7f2a4437e2eca14893ec3f70d08469))
* add playtime heatmap to dashboard and game pages ([8b5fa0f](https://github.com/kanjieater/OmniSave/commit/8b5fa0fc330003847a1ad827be83ef70fb2b09ba))
* add server-driven PDM offset tracking for activity backfill ([1ccd3ea](https://github.com/kanjieater/OmniSave/commit/1ccd3ea1c6cd89b1f8fc84b203d4343c67c95745))
* attribute playtime sessions to the correct OmniSave user via profile map ([0a30b74](https://github.com/kanjieater/OmniSave/commit/0a30b740a96f80befefc19ce35637d426b709196))
* auto-generate openapi.json in CI ([8d3ec54](https://github.com/kanjieater/OmniSave/commit/8d3ec543943808bcfdca31ef1ac259b4c4903ecb))
* auto-generate openapi.json in CI + restore gen_openapi.sh ([2766311](https://github.com/kanjieater/OmniSave/commit/2766311954919c98153a239acbedb5083e1bad4d))
* platform-agnostic activity event ingestion ([5fdb97c](https://github.com/kanjieater/OmniSave/commit/5fdb97c75a2d312c9212a755c816dd9207831c79))
* playtime heatmap on dashboard and game pages ([459bb38](https://github.com/kanjieater/OmniSave/commit/459bb38e9e76b9fffe1e66eb46fc834ff0f58bd5))
* playtime heatmap, activity backfill, and sub-minute session display ([3a67a74](https://github.com/kanjieater/OmniSave/commit/3a67a74029d2333788f72cc336783ea4fefbd9f7))
* rich heatmap tooltip, per-game breakdown, year nav, stats bar ([6af8a27](https://github.com/kanjieater/OmniSave/commit/6af8a273ff4379320e1bfdc7997f26690b9865eb))


### Bug Fixes

* add sys.path so import works when python runs outside pytest ([d305b3f](https://github.com/kanjieater/OmniSave/commit/d305b3f214db6c6b7239ecb14b8fe640083de0f4))
* address PR [#30](https://github.com/kanjieater/OmniSave/issues/30) review — atomicity, auth dedup, sql style ([979f9d3](https://github.com/kanjieater/OmniSave/commit/979f9d3d147f5d1b360aca53030c0d57e2270866))
* address PR 33 activity-event review findings ([b7e0bb8](https://github.com/kanjieater/OmniSave/commit/b7e0bb803930b6c0359adc5b32ccdf0989ab85e3))
* address PR 33 activity-event review findings ([6c7cb1d](https://github.com/kanjieater/OmniSave/commit/6c7cb1d0e8b7d184c2dab0fdfc032ac61abbc44d))
* atomic profile registration + immediate UI refresh on device add ([7bbea4e](https://github.com/kanjieater/OmniSave/commit/7bbea4e2a958489d8ea8cffb964538fd41772e67))
* auto-claim device owner profile on first upload ([5be9a00](https://github.com/kanjieater/OmniSave/commit/5be9a005d578e03f10f7620aba82c4f425aa6f8f))
* auto-claim device owner's profile on first upload ([d0647ef](https://github.com/kanjieater/OmniSave/commit/d0647ef3f9ea6923f84623c8cb37cecd6d622abb))
* auto-claim profile at pair time when device-config arrives first ([126bf13](https://github.com/kanjieater/OmniSave/commit/126bf139ef8745498ff2a52ce705084605ad701d))
* clamp tooltip within viewport edges + show day total in header ([1de7226](https://github.com/kanjieater/OmniSave/commit/1de72266ec3bcabdc72ea5380abf24a1bfbb0665))
* correct DST streak bugs and per-game minute truncation ([41a786a](https://github.com/kanjieater/OmniSave/commit/41a786a8eda299f62b0ea78bd4a7c4c7bf7f9435))
* enable heatmap tooltip on mobile tap ([2a2880e](https://github.com/kanjieater/OmniSave/commit/2a2880e6249e15e1e4120bd212bad97070ca0415))
* enlarge tooltip rows to match activity log sizing ([b041c1e](https://github.com/kanjieater/OmniSave/commit/b041c1e318d218e5456937560070f18f12246c08))
* move claim_pairing_code inside BEGIN IMMEDIATE in pair_by_code ([17b0f2c](https://github.com/kanjieater/OmniSave/commit/17b0f2cf51478012661eca0c4c9718317312614c))
* move claim_pairing_code inside BEGIN IMMEDIATE in pair_by_code ([3de1f30](https://github.com/kanjieater/OmniSave/commit/3de1f30097d5d1a129a2d51bcddc21878b934ec9))
* remove onOpenChange so Radix can't immediately close touch-opened tooltip ([a40b679](https://github.com/kanjieater/OmniSave/commit/a40b6795323a222cca3f2dc3f0a3e030effd26a7))
* replace Radix Tooltip with custom portal for heatmap cells ([55f9b36](https://github.com/kanjieater/OmniSave/commit/55f9b36ba9193f86bca6848b2e2cf4643964af62))
* replace SQL JOIN with per-device session state machine for playtime ([6a217f9](https://github.com/kanjieater/OmniSave/commit/6a217f9c9a1be234f8a26b9a9dbc3df563de72c3))
* replace Today stat with All time total using consistent floor-once formula ([9e54247](https://github.com/kanjieater/OmniSave/commit/9e542473f0d201363b406d3c61c99233091a6f4d))
* resolve game display names via titledb instead of empty labels table ([652ecc8](https://github.com/kanjieater/OmniSave/commit/652ecc81fbdd9734174250b9b86872f76c5ab4d4))
* resolve merge conflicts, lint, transaction hardening for pair_by_code ([22bc4d8](https://github.com/kanjieater/OmniSave/commit/22bc4d846459227e31caa08751257e6fe0478c4d))
* resolve PR [#31](https://github.com/kanjieater/OmniSave/issues/31) round-6 review — display_name/icon enrichment + tooltip total consistency ([66cad8a](https://github.com/kanjieater/OmniSave/commit/66cad8ab02c9df90f1dca92b457b3bfdabf6fb5a))
* resolve test regressions from UUID path param annotations ([0fab526](https://github.com/kanjieater/OmniSave/commit/0fab526fd630e02ec03665e5e101fd8b1b509844))
* restore Pydantic batch cap gate and correct tooltipMinutes formula ([b2c2aca](https://github.com/kanjieater/OmniSave/commit/b2c2aca0c8be8b02f27de6170af6665a36921ade))
* ruff format activity_api.py and game_meta.py ([660b8f5](https://github.com/kanjieater/OmniSave/commit/660b8f51e676053d4315ef04ea8a9857fc34ad27))
* show '&lt; 1m' instead of '0m' for sub-minute game sessions in tooltip ([640438f](https://github.com/kanjieater/OmniSave/commit/640438fc44d68440c6ed005973c558de663e1a71))
* show games and &lt; 1m label for sub-minute playtime sessions ([67671a5](https://github.com/kanjieater/OmniSave/commit/67671a5f3f932b8e5880e57d3eaa5dcb02a31e05))
* show pointer cursor on year nav chevrons ([83eea40](https://github.com/kanjieater/OmniSave/commit/83eea40ebc1fb21d40493888c0a80f6e2fa1cefb))
* validate app event application_id + return total_sec per game ([f943b03](https://github.com/kanjieater/OmniSave/commit/f943b03c3ac16f126fe4537ed9cd755161a26495))
* wrap auto-claim writes in BEGIN IMMEDIATE transaction ([5a674d6](https://github.com/kanjieater/OmniSave/commit/5a674d6694b9a06e79143b923a31fa46cc53573a))

## [1.3.1](https://github.com/kanjieater/OmniSave/compare/v1.3.0...v1.3.1) (2026-06-23)


### Bug Fixes

* use GH_PAT in release-please so tag push triggers server-publish ([593237a](https://github.com/kanjieater/OmniSave/commit/593237a88133510b30d6434cf312fa4f1f5491c6))

## [1.3.0](https://github.com/kanjieater/OmniSave/compare/v1.2.0...v1.3.0) (2026-06-23)


### Features

* add demo video to README beneath frontend screenshot ([4b6d61c](https://github.com/kanjieater/OmniSave/commit/4b6d61c71a1526f68a5df7f9b8bbfa8817a99f8a))
* add RomM title-ID index, auto-claim device profiles, and refresh on settings save ([f8ce8ae](https://github.com/kanjieater/OmniSave/commit/f8ce8aed12fef71638fb8690bca2d12984a72f04))
* populate server repository from OmniSave monorepo split ([68db68e](https://github.com/kanjieater/OmniSave/commit/68db68e76c8991501f073346abfd08c41b9469e2))
* publish API docs to GitHub Pages via swagger-ui ([45c813c](https://github.com/kanjieater/OmniSave/commit/45c813c9264a88808da6504036af7c7d10b44390))
* set version to v1.0.0 across server, add about section to settings ([2608a4c](https://github.com/kanjieater/OmniSave/commit/2608a4c0be53a0e2d301510192a877735655dba2))
* show server version and GitHub link at bottom of Settings page ([549697d](https://github.com/kanjieater/OmniSave/commit/549697d0890c302b64171b1e5e386826c48bb81b))


### Bug Fixes

* add contents:read permission to labels sync workflow ([ac72830](https://github.com/kanjieater/OmniSave/commit/ac728300c280b93d050c397d333b67e432d751c7))
* address pr25 review — atomic sole-profile check, sentinel constant, test precision ([8da410b](https://github.com/kanjieater/OmniSave/commit/8da410b13b6e660fa65d9e1a512fd0fec49053d8))
* cap queue response at 50 READY_FOR_RESTORE items per poll cycle (FIFO) ([275c5ef](https://github.com/kanjieater/OmniSave/commit/275c5efa9851ce5da53753f7e2046bcce600e3f1))
* clear RomM last_played after save upload; fix server.sh dangling symlink ([aa64947](https://github.com/kanjieater/OmniSave/commit/aa64947c010f4b35ff10c8cbda4bbf90aef4ccaf))
* convert stateDiagram-v2 to flowchart TD for reliable GitHub rendering ([9ef5ea7](https://github.com/kanjieater/OmniSave/commit/9ef5ea7bf4d8c27434f994d6f2d0337fa92a4013))
* document co-claim as intentional design (family-trust model) ([7daacee](https://github.com/kanjieater/OmniSave/commit/7daaceeb861b4a6bb709a55be7abb69cada5dbd4))
* enable Pages via configure-pages enablement flag ([4fd80d5](https://github.com/kanjieater/OmniSave/commit/4fd80d58bbb25d34a62e298c7df2c6caadc992aa))
* exclude romm-as-source saves from _romm_unsynced_count ([aef7a04](https://github.com/kanjieater/OmniSave/commit/aef7a04b00752f133a4b25cf6d16ca87f116269d))
* full-length demo GIF covering complete 24s video ([e3ae9c0](https://github.com/kanjieater/OmniSave/commit/e3ae9c0bcb4b8db8b0b368fab83ff241ac837c89))
* isolate save ownership to device profiles, not device owner ([#23](https://github.com/kanjieater/OmniSave/issues/23)) ([adb3fd4](https://github.com/kanjieater/OmniSave/commit/adb3fd4cc7cfc2a86d32ee1140e2d511d6198a97))
* manifest re-post returns actual server_verified_bytes for upload resume ([d4f77d7](https://github.com/kanjieater/OmniSave/commit/d4f77d74883e8f7cbc35f4abc8c3fb22f4743f8f))
* migration atomicity and profile sort determinism ([#24](https://github.com/kanjieater/OmniSave/issues/24)) ([5f63e2d](https://github.com/kanjieater/OmniSave/commit/5f63e2ddc447142595e536cd4d291f3abfc4ea0e))
* optimistic auth — show main UI immediately if token exists in localStorage ([6a27504](https://github.com/kanjieater/OmniSave/commit/6a27504b25d2ca17a1ebbf3e08c5f3505d096de6))
* parallel RomM scan, titledb deadlock, and auto-enable on connect ([627f165](https://github.com/kanjieater/OmniSave/commit/627f165b3496a7f2d54d5f80ae342eb15dedc3d8))
* poll profiles every 3s while empty after pair ([2c5d2cb](https://github.com/kanjieater/OmniSave/commit/2c5d2cbcffd77ebb1779ba33c17644004fbd3587))
* prevent Docker DNS alias collision between PROD and DEV instances ([e35e00e](https://github.com/kanjieater/OmniSave/commit/e35e00e006773ed1e91ccbb3815b038665a34dae))
* remove direction LR and special chars from stateDiagram-v2 blocks ([fd230bd](https://github.com/kanjieater/OmniSave/commit/fd230bd94b9a60fe79ee81552dc8b6ba2a9865f3))
* remove gate 5 from _effective_sync_state — games uploaded before ([27a0faa](https://github.com/kanjieater/OmniSave/commit/27a0faa39c52fe096a38c8a1d51ab2be9b35892e))
* replace mermaid blocks with mermaid.ink pre-rendered images ([841199a](https://github.com/kanjieater/OmniSave/commit/841199acd3f33b788c0eea053df65143c7fcdd9d))
* replace native download link with fetch+Bearer ([#18](https://github.com/kanjieater/OmniSave/issues/18)) ([f958f6a](https://github.com/kanjieater/OmniSave/commit/f958f6a49f138cf2e40131965ff4e316c3d6f685))
* replace unsupported bidirectional mermaid arrow ([4c3b585](https://github.com/kanjieater/OmniSave/commit/4c3b585107efccb853ae911b2e61e794f51d86f1))
* replace video tag with animated GIF for GitHub README inline playback ([a98e1a0](https://github.com/kanjieater/OmniSave/commit/a98e1a072bc1b9f33a2b7c37a5766ae8bdeb1036))
* resolve all ruff lint errors and fix test workflow path ([8828acb](https://github.com/kanjieater/OmniSave/commit/8828acbc800ca72952c08beca1124e9a42867ff3))
* restore always-on auto-claim, 404 on inaccessible games, Enter on RomM form ([cae655d](https://github.com/kanjieater/OmniSave/commit/cae655d7b78b4dffb9e4ebe0f458b334a3eabba0))
* retry authStatus false-with-token; make auth_status async to avoid _conn race ([e651c86](https://github.com/kanjieater/OmniSave/commit/e651c86785a062c3b4b1b6c380867a08a2d81405))
* retry authStatus when server returns authenticated:false with stored token ([e5d1a09](https://github.com/kanjieater/OmniSave/commit/e5d1a09a1b5412917ebe46028b8b0f3619ec2765))
* retry authStatus() after login and increase startup check retries ([#20](https://github.com/kanjieater/OmniSave/issues/20)) ([4c210b2](https://github.com/kanjieater/OmniSave/commit/4c210b2755ebe08ed77b6d0d9e75a9929807cb13))
* retry login on transient network error ([#19](https://github.com/kanjieater/OmniSave/issues/19)) ([64050a6](https://github.com/kanjieater/OmniSave/commit/64050a694bf2b5d9e2f1cc8f8389d4dbc4e4c5a9))
* romm file-only title matching, 403 no-retry, admin rename cascade, and UI error banners ([8dab294](https://github.com/kanjieater/OmniSave/commit/8dab294954a535997e477b28c023b614e8385aca))
* set default profile on auto-claim; show This is me for all unclaimed-by-me profiles ([717158a](https://github.com/kanjieater/OmniSave/commit/717158afb9da993b7e00cf8e7c43b07670613727))
* show reconnect screen instead of login form on transient startup failure ([5f8ae31](https://github.com/kanjieater/OmniSave/commit/5f8ae312403ff63ff4a9ac95b2600b76c987d8b6))
* suppress auto-claim for multi-profile devices ([a5d0e85](https://github.com/kanjieater/OmniSave/commit/a5d0e8574e9dbed1401b9ac0edd92a90c172ca36))
* suppress auto-claim for multi-profile devices ([#25](https://github.com/kanjieater/OmniSave/issues/25)) ([3bf90a3](https://github.com/kanjieater/OmniSave/commit/3bf90a3c20ce8e02cb702ece8184f989c2dffc7f))
* surface RomM auth errors and gate device visibility on verified credentials ([4c9eeac](https://github.com/kanjieater/OmniSave/commit/4c9eeac15aae249a4b9031c6562c353327fdbaad))
* trigger romm index on re-enable + replace toggle with Connect/Disable button ([#22](https://github.com/kanjieater/OmniSave/issues/22)) ([e49ff7c](https://github.com/kanjieater/OmniSave/commit/e49ff7ca4a98957fbe72940b3ec3e9a02781f712))
* unify frontend pending count via isPendingDelivery helper ([54e6279](https://github.com/kanjieater/OmniSave/commit/54e62791bfa388c4ffa2aa1b8041868dc5699b05))
* unify pending definition — outbound READY_FOR_RESTORE only ([74bd512](https://github.com/kanjieater/OmniSave/commit/74bd512aece55b7118fc31e85d67dba178399902))
* use GH_PAT for GHCR login when available (private repo workaround) ([a0b0eb1](https://github.com/kanjieater/OmniSave/commit/a0b0eb1cda601fb85fe6618d6caaeb8dc3d825ef))
* use noqa: B008 for FastAPI Body() defaults, reformat ([b563730](https://github.com/kanjieater/OmniSave/commit/b563730af404ffa5f39891e9f61b1baa1e41d52d))
* use release CDN URL for demo video to enable GitHub README playback ([a5512f5](https://github.com/kanjieater/OmniSave/commit/a5512f5eff30f6d068b777dc5bab852c396ccd3e))


### Reverts

* remove clear_last_played RomM play-history modification ([cd44547](https://github.com/kanjieater/OmniSave/commit/cd445478db6f2c5dfb84e2766306478c9df0d84d))

## [1.2.0](https://github.com/kanjieater/OmniSave/compare/v1.1.0...v1.2.0) (2026-06-23)


### Features

* add demo video to README beneath frontend screenshot ([4b6d61c](https://github.com/kanjieater/OmniSave/commit/4b6d61c71a1526f68a5df7f9b8bbfa8817a99f8a))
* add RomM title-ID index, auto-claim device profiles, and refresh on settings save ([f8ce8ae](https://github.com/kanjieater/OmniSave/commit/f8ce8aed12fef71638fb8690bca2d12984a72f04))


### Bug Fixes

* address pr25 review — atomic sole-profile check, sentinel constant, test precision ([8da410b](https://github.com/kanjieater/OmniSave/commit/8da410b13b6e660fa65d9e1a512fd0fec49053d8))
* cap queue response at 50 READY_FOR_RESTORE items per poll cycle (FIFO) ([275c5ef](https://github.com/kanjieater/OmniSave/commit/275c5efa9851ce5da53753f7e2046bcce600e3f1))
* clear RomM last_played after save upload; fix server.sh dangling symlink ([aa64947](https://github.com/kanjieater/OmniSave/commit/aa64947c010f4b35ff10c8cbda4bbf90aef4ccaf))
* convert stateDiagram-v2 to flowchart TD for reliable GitHub rendering ([9ef5ea7](https://github.com/kanjieater/OmniSave/commit/9ef5ea7bf4d8c27434f994d6f2d0337fa92a4013))
* document co-claim as intentional design (family-trust model) ([7daacee](https://github.com/kanjieater/OmniSave/commit/7daaceeb861b4a6bb709a55be7abb69cada5dbd4))
* exclude romm-as-source saves from _romm_unsynced_count ([aef7a04](https://github.com/kanjieater/OmniSave/commit/aef7a04b00752f133a4b25cf6d16ca87f116269d))
* full-length demo GIF covering complete 24s video ([e3ae9c0](https://github.com/kanjieater/OmniSave/commit/e3ae9c0bcb4b8db8b0b368fab83ff241ac837c89))
* isolate save ownership to device profiles, not device owner ([#23](https://github.com/kanjieater/OmniSave/issues/23)) ([adb3fd4](https://github.com/kanjieater/OmniSave/commit/adb3fd4cc7cfc2a86d32ee1140e2d511d6198a97))
* manifest re-post returns actual server_verified_bytes for upload resume ([d4f77d7](https://github.com/kanjieater/OmniSave/commit/d4f77d74883e8f7cbc35f4abc8c3fb22f4743f8f))
* migration atomicity and profile sort determinism ([#24](https://github.com/kanjieater/OmniSave/issues/24)) ([5f63e2d](https://github.com/kanjieater/OmniSave/commit/5f63e2ddc447142595e536cd4d291f3abfc4ea0e))
* optimistic auth — show main UI immediately if token exists in localStorage ([6a27504](https://github.com/kanjieater/OmniSave/commit/6a27504b25d2ca17a1ebbf3e08c5f3505d096de6))
* parallel RomM scan, titledb deadlock, and auto-enable on connect ([627f165](https://github.com/kanjieater/OmniSave/commit/627f165b3496a7f2d54d5f80ae342eb15dedc3d8))
* poll profiles every 3s while empty after pair ([2c5d2cb](https://github.com/kanjieater/OmniSave/commit/2c5d2cbcffd77ebb1779ba33c17644004fbd3587))
* prevent Docker DNS alias collision between PROD and DEV instances ([e35e00e](https://github.com/kanjieater/OmniSave/commit/e35e00e006773ed1e91ccbb3815b038665a34dae))
* remove direction LR and special chars from stateDiagram-v2 blocks ([fd230bd](https://github.com/kanjieater/OmniSave/commit/fd230bd94b9a60fe79ee81552dc8b6ba2a9865f3))
* remove gate 5 from _effective_sync_state — games uploaded before ([27a0faa](https://github.com/kanjieater/OmniSave/commit/27a0faa39c52fe096a38c8a1d51ab2be9b35892e))
* replace mermaid blocks with mermaid.ink pre-rendered images ([841199a](https://github.com/kanjieater/OmniSave/commit/841199acd3f33b788c0eea053df65143c7fcdd9d))
* replace native download link with fetch+Bearer ([#18](https://github.com/kanjieater/OmniSave/issues/18)) ([f958f6a](https://github.com/kanjieater/OmniSave/commit/f958f6a49f138cf2e40131965ff4e316c3d6f685))
* replace video tag with animated GIF for GitHub README inline playback ([a98e1a0](https://github.com/kanjieater/OmniSave/commit/a98e1a072bc1b9f33a2b7c37a5766ae8bdeb1036))
* restore always-on auto-claim, 404 on inaccessible games, Enter on RomM form ([cae655d](https://github.com/kanjieater/OmniSave/commit/cae655d7b78b4dffb9e4ebe0f458b334a3eabba0))
* retry authStatus false-with-token; make auth_status async to avoid _conn race ([e651c86](https://github.com/kanjieater/OmniSave/commit/e651c86785a062c3b4b1b6c380867a08a2d81405))
* retry authStatus when server returns authenticated:false with stored token ([e5d1a09](https://github.com/kanjieater/OmniSave/commit/e5d1a09a1b5412917ebe46028b8b0f3619ec2765))
* retry authStatus() after login and increase startup check retries ([#20](https://github.com/kanjieater/OmniSave/issues/20)) ([4c210b2](https://github.com/kanjieater/OmniSave/commit/4c210b2755ebe08ed77b6d0d9e75a9929807cb13))
* retry login on transient network error ([#19](https://github.com/kanjieater/OmniSave/issues/19)) ([64050a6](https://github.com/kanjieater/OmniSave/commit/64050a694bf2b5d9e2f1cc8f8389d4dbc4e4c5a9))
* romm file-only title matching, 403 no-retry, admin rename cascade, and UI error banners ([8dab294](https://github.com/kanjieater/OmniSave/commit/8dab294954a535997e477b28c023b614e8385aca))
* set default profile on auto-claim; show This is me for all unclaimed-by-me profiles ([717158a](https://github.com/kanjieater/OmniSave/commit/717158afb9da993b7e00cf8e7c43b07670613727))
* show reconnect screen instead of login form on transient startup failure ([5f8ae31](https://github.com/kanjieater/OmniSave/commit/5f8ae312403ff63ff4a9ac95b2600b76c987d8b6))
* suppress auto-claim for multi-profile devices ([a5d0e85](https://github.com/kanjieater/OmniSave/commit/a5d0e8574e9dbed1401b9ac0edd92a90c172ca36))
* suppress auto-claim for multi-profile devices ([#25](https://github.com/kanjieater/OmniSave/issues/25)) ([3bf90a3](https://github.com/kanjieater/OmniSave/commit/3bf90a3c20ce8e02cb702ece8184f989c2dffc7f))
* surface RomM auth errors and gate device visibility on verified credentials ([4c9eeac](https://github.com/kanjieater/OmniSave/commit/4c9eeac15aae249a4b9031c6562c353327fdbaad))
* trigger romm index on re-enable + replace toggle with Connect/Disable button ([#22](https://github.com/kanjieater/OmniSave/issues/22)) ([e49ff7c](https://github.com/kanjieater/OmniSave/commit/e49ff7ca4a98957fbe72940b3ec3e9a02781f712))
* unify frontend pending count via isPendingDelivery helper ([54e6279](https://github.com/kanjieater/OmniSave/commit/54e62791bfa388c4ffa2aa1b8041868dc5699b05))
* unify pending definition — outbound READY_FOR_RESTORE only ([74bd512](https://github.com/kanjieater/OmniSave/commit/74bd512aece55b7118fc31e85d67dba178399902))
* use release CDN URL for demo video to enable GitHub README playback ([a5512f5](https://github.com/kanjieater/OmniSave/commit/a5512f5eff30f6d068b777dc5bab852c396ccd3e))


### Reverts

* remove clear_last_played RomM play-history modification ([cd44547](https://github.com/kanjieater/OmniSave/commit/cd445478db6f2c5dfb84e2766306478c9df0d84d))

## [1.1.0](https://github.com/kanjieater/OmniSave/compare/v1.0.0...v1.1.0) (2026-06-09)


### Features

* populate server repository from OmniSave monorepo split ([68db68e](https://github.com/kanjieater/OmniSave/commit/68db68e76c8991501f073346abfd08c41b9469e2))
* publish API docs to GitHub Pages via swagger-ui ([45c813c](https://github.com/kanjieater/OmniSave/commit/45c813c9264a88808da6504036af7c7d10b44390))
* set version to v1.0.0 across server, add about section to settings ([2608a4c](https://github.com/kanjieater/OmniSave/commit/2608a4c0be53a0e2d301510192a877735655dba2))
* show server version and GitHub link at bottom of Settings page ([549697d](https://github.com/kanjieater/OmniSave/commit/549697d0890c302b64171b1e5e386826c48bb81b))


### Bug Fixes

* add contents:read permission to labels sync workflow ([ac72830](https://github.com/kanjieater/OmniSave/commit/ac728300c280b93d050c397d333b67e432d751c7))
* enable Pages via configure-pages enablement flag ([4fd80d5](https://github.com/kanjieater/OmniSave/commit/4fd80d58bbb25d34a62e298c7df2c6caadc992aa))
* replace unsupported bidirectional mermaid arrow ([4c3b585](https://github.com/kanjieater/OmniSave/commit/4c3b585107efccb853ae911b2e61e794f51d86f1))
* resolve all ruff lint errors and fix test workflow path ([8828acb](https://github.com/kanjieater/OmniSave/commit/8828acbc800ca72952c08beca1124e9a42867ff3))
* use GH_PAT for GHCR login when available (private repo workaround) ([a0b0eb1](https://github.com/kanjieater/OmniSave/commit/a0b0eb1cda601fb85fe6618d6caaeb8dc3d825ef))
* use noqa: B008 for FastAPI Body() defaults, reformat ([b563730](https://github.com/kanjieater/OmniSave/commit/b563730af404ffa5f39891e9f61b1baa1e41d52d))

## Changelog

All notable changes to this project will be documented in this file.

See [Conventional Commits](https://conventionalcommits.org) for commit guidelines.
