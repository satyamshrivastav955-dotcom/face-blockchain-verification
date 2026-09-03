# `input/` — put your query image here

Drop the photograph you want to verify in this directory and point `register` at it:

```bash
python -m src.main register --image input/sample.jpg
```

Everything in here except this file and `.gitkeep` is gitignored, deliberately. A photograph of a
face is personal data, and committing one to a public repository is not something that should happen
by accident.

## Choosing an image

The pipeline needs a reverse-image search to find the same face somewhere on the web, so the input
has to be an image that is *already published* — or one whose subject also appears in a published
post. A photo that exists nowhere but your hard drive will correctly return exit code 5, no
confirmed match. That is a valid demonstration, but it is not the happy path.

What works well: your own profile picture from a public social account; a clearly public-figure
press photo; any consenting subject whose photo you have permission to upload.

What to avoid: a photograph of someone who has not agreed to it. Note that with the default
configuration the query image is **uploaded to a third-party host** so Google Lens can fetch it —
see the privacy section of the main README. `PUBLISH_PROVIDER=none` with `--image-url` avoids the
upload if you host the image yourself, and TinEye accepts a direct upload instead.

Practical notes: a single clearly-visible face works best, since only the highest-confidence
detection is used; a face smaller than roughly 80×80 pixels tends to embed poorly; and heavy
filters, extreme pose or occlusion usually cause a false reject rather than a false accept, which is
the safer direction to fail.

## No image, no keys, no network?

The repository ships a synthetic offline fixture so the whole pipeline can be exercised without any
of that. See `tests/data/README.md`.
