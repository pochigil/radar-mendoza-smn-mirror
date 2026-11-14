# radar-mendoza-smn-mirror

A copy of the CAP alert feeds of the [Servicio Meteorológico Nacional](https://www.smn.gob.ar/) (SMN), refreshed every 5 minutes by GitHub Actions and served by GitHub Pages at <https://pochigil.github.io/radar-mendoza-smn-mirror/>.

Why: the Radar Mendoza API runs on Cloudflare Workers, whose outgoing IP is shared with many other users, so the SMN rate limit (180 requests per 10 minutes per IP) is always used up there. The Worker reads this copy instead. Each run downloads only new files, well under that limit.

| Path | What |
|---|---|
| `feeds/index.xml` | `https://ssl.smn.gob.ar/CAP/AR.php` |
| `feeds/short-term.xml` | `https://ssl.smn.gob.ar/feeds/CAP/avisocortoplazo/rss_acpCAP.xml` |
| `files/<host>/<path>` | Each CAP file listed in the feeds (empty when the SMN answered 404) |
| `status.json` | When each feed was last copied successfully |

No parsing happens here: the API parses and filters. Nothing secret lives in this repo.

Data: Servicio Meteorológico Nacional (SMN), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). This copy is unofficial and unchanged.
