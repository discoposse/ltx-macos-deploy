# oMLX in this lab

oMLX is a **local LLM server**. This lab uses it to **rewrite video prompts**. It does not generate mp4s. LTX-2 distilled still does that.

```
Generate prompt  →  oMLX /v1/chat/completions (optional rewrite, KV cache)
                 →  LTX-2 worker (load / encode / denoise / write mp4)
```

The shared rewrite instruction is sent as a stable system prefix. oMLX stores KV blocks in RAM (hot) and `~/.omlx/cache` (SSD). The second rewrite of any prompt should report `cached_tokens` on that prefix. Cache hits need streaming usage; the lab always streams.

## Configure the backend in oMLX

The lab does not own the model weights or the cache disks. Point oMLX at the model you want, then generate here.

1. Start oMLX (`omlx start` or oMLX.app) and open [http://127.0.0.1:8000/admin](http://127.0.0.1:8000/admin).
2. **Models**: download or load one LLM, then set it as default. Unload extras so LTX still has unified memory.
3. **Cache / global settings**: set the SSD cache directory (default `~/.omlx/cache`), SSD max size, and hot-cache size. `hot_cache_max_size` of `0` means SSD-only (blocks on disk, not a RAM copy). Applying cache settings unloads models; load the default again.
4. Back in this lab, Status and Generate show the resolved model, models dir, SSD path, and hot cap. Generate lets you pick among loaded models; the default from oMLX is used if you do not.
5. **Rewrite with oMLX**, then **Generate**. The run writes `runs/{id}/omlx.json` with those paths plus a cache probe (hot / SSD / cold blocks). Open **Report** for the storage and caching panel.

```
oMLX admin (model + SSD/hot dirs)
        ↓
Generate rewrite  →  /v1/chat/completions  +  /admin/api/cache/probe
        ↓
runs/{id}/omlx.json  →  Report "oMLX cache"
        ↓
LTX-2 worker (mp4)
```

This lab never binds port 8000 and `./labctl down` does not stop oMLX.

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
Models: `~/.omlx/models` (override in oMLX admin)  
SSD cache: oMLX admin Cache settings, or `~/.omlx/settings.json` → `cache.ssd_cache_dir` (default `~/.omlx/cache`)  
Hot RAM: `cache.hot_cache_max_size` (`0` = SSD-only)

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

1. Status: optional component **oMLX prompt rewrite** is up. The **oMLX backend** tile shows the default model, models dir, and SSD path. Open **oMLX admin** if you need to load a different model or move the cache.
2. Generate: pick the oMLX model (defaults to whatever is loaded in the admin), write a prompt, click **Rewrite with oMLX**. The rewritten text replaces the prompt. The line under the button shows `cached tokens / prompt tokens` and a probe of hot / SSD / cold blocks.
3. Click **Rewrite with oMLX** again (same or different user text). The system prefix is unchanged, so `cached_tokens` should jump (block size is 256 tokens) and SSD blocks should rise.
4. Click **Generate**. That still runs LTX-2. The next Report includes an **oMLX cache** panel with the full storage paths.

**CLI**

```bash
./labctl omlx
./labctl omlx snapshot "a red hatchback on a coastal runway"
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
