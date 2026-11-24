# Security

## Reporting

Use GitHub private vulnerability reporting (**Security** → **Report a vulnerability**),
not public issues. Include preconditions, impact and reproduction steps.

## Scope

- Data sent off the machine that [Privacy](docs/privacy.md) says is not sent.
- Secrets the redaction should catch and does not.
- Another local user or process reading `~/.vice/` or using the service socket.
- Source or query content causing vice to execute or write anything.

## Design

- Query and source text reaches Jev only as data. Jev returns probabilities; code
  decides.
- The `command` output runs a configured argv with JSON on stdin. No shell, and no event
  or source text on the command line.
- `~/.vice/` and the service socket are owner-only.
- The API key is stored in the Keychain.
