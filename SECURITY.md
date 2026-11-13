# Security

vice handles private notes, clipboard contents and an API key. Reports are taken seriously.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting: on the repository page, open the
**Security** tab and choose **Report a vulnerability**. Do not open a public issue for
anything that could expose a user's data.

Useful to include: what an attacker needs, what they gain, and steps to reproduce.

## In scope

- Anything that sends data off the machine that [docs/privacy.md](docs/privacy.md) says
  is not sent.
- Secrets that the local redaction should catch and does not.
- Ways for another local user or process to read `~/.vice/` or send commands to the
  service socket.
- Ways for the content of a note, a clipboard entry or a dropped file to cause vice to
  run something or write somewhere it should not.

## Design notes relevant to security

- Text from events and notes is only ever passed to Jev as data to be judged. Jev returns
  probabilities, not text or instructions, and code alone decides what happens.
- The `command` output runs a fixed program from your configuration with JSON on stdin.
  No shell is invoked and nothing from a note or event becomes part of the command line.
- The service socket and `~/.vice/` are restricted to the owning user.
- The API key is stored in the system keychain.
