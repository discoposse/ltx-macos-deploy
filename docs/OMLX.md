# oMLX in this lab

oMLX is a **local LLM server**. This lab uses it to **rewrite video prompts**. It does not generate mp4s. LTX-2 distilled still does that.

```
Generate prompt  →  oMLX /v1/chat/completions (optional rewrite, KV cache)
                 →  LTX-2 worker (load / encode / denoise / write mp4)
```

The shared rewrite instruction is sent as a stable system prefix. oMLX stores KV blocks in RAM (hot) and `~/.omlx/cache` (SSD). The second rewrite of any prompt should report `cached_tokens` on that prefix. Cache hits need streaming usage; the lab always streams.

## Install and start

oMLX is not started by `./labctl up`. Run it yourself, then leave it on `:8000`.

```bash
# Homebrew
brew tap jundot/omlx https://github.com/jundot/omlx
brew install jundot/omlx/omlx
omlx start

# or open /Applications/oMLX.app and start the server from the menu bar
```

Admin UI: http://127.0.0.1:8000/admin  
Chat UI: http://127.0.0.1:8000/admin/chat  
Models: `~/.omlx/models`  
SSD cache: `~/.omlx/settings.json` → `cache.ssd_cache_dir` (default `~/.omlx/cache`)

This lab never binds port 8000 and `./labctl down` does not stop oMLX.

## API key

`/v1/models` and chat require a key. The lab reads, in order:

1. `OMLX_API_KEY`
2. `auth.api_key` in `~/.omlx/settings.json`

It never returns the key to the browser.

```bash
export OMLX_API_KEY=your-key   # only if you do not want the settings.json fallback
./labctl omlx                  # should print "ready": true
```

## Use it

**Console**

1. Status: optional component **oMLX prompt rewrite** is up, and the oMLX engine card is ready.
2. Generate: write a prompt, click **Rewrite with oMLX**. The rewritten text replaces the prompt. The line under the button shows `cached tokens / prompt tokens`.
3. Click **Rewrite with oMLX** again (same or different user text). The system prefix is unchanged, so `cached_tokens` should jump (block size is 256 tokens).
4. Click **Generate**. That still runs LTX-2.

**CLI**

```bash
./labctl omlx
./labctl omlx rewrite "a red hatchback on a coastal runway"
./labctl omlx rewrite "a red hatchback on a coastal runway"   # expect cached_tokens > 0
./labctl url omlx
./labctl omlx clear-cache   # next rewrite is a cold prefill
```

## Memory

Do not keep a large oMLX model loaded during a long LTX run on a tight Mac. Unified memory is shared. Unload extra models in the oMLX admin, or stop oMLX (`omlx stop`) while generating 97- or 193-frame clips.

## What this is not

- Not an LTX video backend.
- Not a replacement for the LTX Gemma text encoder (`gemma4-12b-with-proj-ltx-2.5`).
- Generic `/v1/embeddings` is the wrong tensor for LTX.
