# Changelog

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
