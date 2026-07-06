# Repo conventions

Adopted from the sibling `monitoring` project so this repo stays consistent with
the rest of the fleet.

## Commits

- **Scoped subject**: `<scope>: <what changed>`, where scope is a component
  (`capture:`, `docker:`, `compose:`, `assemble:`) or a category (`Docs:`,
  `Plan:`, `Security:`, `repo:`). Specific and to the point — no "Step N",
  "misc", or bare "update".
- **Body**: explain the *why* and the effect, wrapped at ~75 chars, as prose
  rather than a bullet dump of the diff. Omit only for trivial changes.
- **Trailer**: end with
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.
- Commit in small, coherent steps; don't bundle unrelated changes.

## Secrets & per-machine config

- Nothing secret or machine-specific in the committed tree. Only `.env` differs
  per machine, and `.env` is **never committed** — commit `.env.example`.
- Config that embeds secrets is **rendered** from a committed `*.template`
  (via `envsubst`); the rendered copy is gitignored, the template is committed.
- Keys and certs (`*.pem`, `*.key`, `*.crt`) and anything under `secrets/`
  stay out of git.

## Public-repo privacy

This repository is **public**. Keep location-revealing values — real latitude /
longitude, camera IP, hostnames — out of the committed tree; they live only in
`.env`. `.env.example` ships placeholder coordinates, never the real site.
