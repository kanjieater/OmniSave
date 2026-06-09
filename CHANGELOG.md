# Changelog

## [1.2.0](https://github.com/kanjieater/OmniSave/compare/v1.1.0...v1.2.0) (2026-06-09)


### Features

* add demo video to README beneath frontend screenshot ([4b6d61c](https://github.com/kanjieater/OmniSave/commit/4b6d61c71a1526f68a5df7f9b8bbfa8817a99f8a))


### Bug Fixes

* clear RomM last_played after save upload; fix server.sh dangling symlink ([aa64947](https://github.com/kanjieater/OmniSave/commit/aa64947c010f4b35ff10c8cbda4bbf90aef4ccaf))
* convert stateDiagram-v2 to flowchart TD for reliable GitHub rendering ([9ef5ea7](https://github.com/kanjieater/OmniSave/commit/9ef5ea7bf4d8c27434f994d6f2d0337fa92a4013))
* full-length demo GIF covering complete 24s video ([e3ae9c0](https://github.com/kanjieater/OmniSave/commit/e3ae9c0bcb4b8db8b0b368fab83ff241ac837c89))
* remove direction LR and special chars from stateDiagram-v2 blocks ([fd230bd](https://github.com/kanjieater/OmniSave/commit/fd230bd94b9a60fe79ee81552dc8b6ba2a9865f3))
* replace mermaid blocks with mermaid.ink pre-rendered images ([841199a](https://github.com/kanjieater/OmniSave/commit/841199acd3f33b788c0eea053df65143c7fcdd9d))
* replace video tag with animated GIF for GitHub README inline playback ([a98e1a0](https://github.com/kanjieater/OmniSave/commit/a98e1a072bc1b9f33a2b7c37a5766ae8bdeb1036))
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
