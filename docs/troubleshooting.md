# Troubleshooting

Start with:

```bash
vice status
```

It shows the key, the configured sources and notes, the index size, and whether the
service is running. Then look at the last few decisions:

```bash
tail -n 5 ~/.vice/decisions.jsonl
```

## "no configuration … Run `vice setup` first"

There is no `~/.vice/config.toml`. Run `vice setup`.

## "unknown key(s) … in [section]"

A key in `config.toml` is misspelled or in the wrong section. The message lists what is
allowed there. See [Configuration](configuration.md).

## "no TypeSafe API key found"

Run `vice key set`. If you rely on `TYPESAFE_API_KEY` in your shell, note that the
background service does not inherit it; store the key in the Keychain instead.

## macOS asks whether Python may access the Keychain

Expected the first time the background service or an assistant starts vice. Choose
"Always Allow" so it does not ask again.

## "cannot reach TypeSafe"

Check your network, and that the key is valid. vice pins a specific Jev model; if that
model has been retired, upgrade vice.

## `vice ask` says "Nothing to show"

It also says why:

- **"this does not look like something that needs your notes"**: the text was judged
  complete as written. Phrase it as a question about something specific.
- **"nothing in your notes answers this"**: no indexed note states the detail. Check the
  note is under a configured source and not excluded, then run `vice sync`.
- **"TypeSafe did not answer in time"**: a slow response. Try again. If it happens often
  on your network, raise `gate_timeout_ms` under `[pipeline]`.

## It shows an outdated fact

vice decides which note is newer from the note's date. If an old note was edited
recently and has no date in its frontmatter or file name, its modification time makes it
look new. Add `date: YYYY-MM-DD` to the frontmatter of notes where this matters.

It can also happen when two notes word the same fact very differently and are not
recognised as conflicting. Measured on test data, a superseded fact slipped through in
about 7% of cases.

## A note I just wrote is not found

The running service re-reads notes every two minutes. To index immediately:

```bash
vice sync
```

## Nothing happens when I copy text

- Clipboard watching is off by default. Check `sources:` in `vice status`.
- The service must be running: `vice start`.
- Most copies are meant to produce nothing. Check `decisions.jsonl` for the reason.

## The service will not start, or keeps stopping

```bash
vice logs
```

The usual causes are a missing key, an invalid `config.toml`, or a notes folder that no
longer exists. Fix the cause, then run `vice start` again.

## The first sync is slow

It downloads a 90 MB model from Hugging Face into `~/.vice/models` and embeds every note.
Later syncs only embed changed text. If the download is blocked on your network, run the
first sync somewhere it is not; after that the model loads offline.
A vault of a few thousand notes takes a minute or two the first time.

## Starting over

Delete the index and rebuild it:

```bash
rm -rf ~/.vice/index
```

```bash
vice sync
```

## Reporting a problem

Open an issue with the output of `vice status` and the relevant line from
`decisions.jsonl`. That line contains the text of the event and of the matched notes;
remove anything private before posting.
