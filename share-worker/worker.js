// Cloudflare Worker — proxy de partage pour Greg TV.
//
// Rôle :
//  - reçoit l'état ON/OFF + chaîne en cours depuis new.html (POST /api/share, protégé par X-Admin-Key)
//  - expose un statut public sans lien réel (GET /api/status)
//  - proxy la playlist HLS et les segments en cachant totalement l'URL/le token d'origine
//    (les URLs des segments sont chiffrées en AES-GCM, jamais transmises en clair au client)
//  - revérifie le flag "enabled" à chaque requête de segment : la coupure est donc
//    quasi instantanée (au pire le temps du segment en cours, qq secondes)
//
// Bindings nécessaires (voir wrangler.toml) :
//  - KV namespace "SHARE_KV"          -> état { enabled, channelUrl, channelName }
//  - secret      "ADMIN_KEY"          -> doit correspondre à SHARE_ADMIN_KEY dans new.html
//  - secret      "ENC_KEY"            -> clé AES-256-GCM en base64 (32 octets), pour chiffrer les URLs de segments

var CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-Admin-Key",
};

export default {
  async fetch(request, env) {
    var url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: CORS_HEADERS });
    }

    if (url.pathname === "/api/share" && request.method === "POST") {
      return handleShareUpdate(request, env);
    }
    if (url.pathname === "/api/status" && request.method === "GET") {
      return handleStatus(env);
    }
    if (url.pathname === "/hls/playlist.m3u8" && request.method === "GET") {
      return handlePlaylist(env);
    }
    if (url.pathname.indexOf("/hls/seg/") === 0 && request.method === "GET") {
      return handleSegment(env, url);
    }

    return new Response("Not found", { status: 404, headers: CORS_HEADERS });
  },
};

async function handleShareUpdate(request, env) {
  var adminKey = request.headers.get("X-Admin-Key");
  if (adminKey !== env.ADMIN_KEY) {
    return new Response("Unauthorized", { status: 401, headers: CORS_HEADERS });
  }

  var body;
  try {
    body = await request.json();
  } catch (e) {
    return new Response("Bad request", { status: 400, headers: CORS_HEADERS });
  }

  var state = {
    enabled: !!body.enabled,
    channelUrl: body.channelUrl || "",
    channelName: body.channelName || "",
    updatedAt: Date.now(),
  };
  await env.SHARE_KV.put("state", JSON.stringify(state));

  return new Response(JSON.stringify({ ok: true }), {
    headers: Object.assign({ "Content-Type": "application/json" }, CORS_HEADERS),
  });
}

async function getState(env) {
  var raw = await env.SHARE_KV.get("state");
  return raw ? JSON.parse(raw) : { enabled: false, channelUrl: "", channelName: "" };
}

async function handleStatus(env) {
  var state = await getState(env);
  // On ne renvoie jamais channelUrl ici : le viewer ne doit voir ni le lien ni le token.
  return new Response(
    JSON.stringify({ enabled: state.enabled, channelName: state.channelName }),
    { headers: Object.assign({ "Content-Type": "application/json" }, CORS_HEADERS) }
  );
}

async function handlePlaylist(env) {
  var state = await getState(env);
  if (!state.enabled || !state.channelUrl) {
    return new Response("Sharing disabled", { status: 403, headers: CORS_HEADERS });
  }

  var upstream = await fetch(state.channelUrl);
  if (!upstream.ok) {
    return new Response("Upstream error", { status: 502, headers: CORS_HEADERS });
  }
  var text = await upstream.text();
  var baseUrl = state.channelUrl.substring(0, state.channelUrl.lastIndexOf("/") + 1);
  var rewritten = await rewriteManifest(text, baseUrl, env);

  return new Response(rewritten, {
    headers: Object.assign(
      { "Content-Type": "application/vnd.apple.mpegurl", "Cache-Control": "no-store" },
      CORS_HEADERS
    ),
  });
}

// Remplace chaque ligne d'URI (segment ou sous-playlist) par un chemin opaque
// /hls/seg/<token chiffré>. Le client ne voit jamais le domaine ni le token réels.
async function rewriteManifest(text, baseUrl, env) {
  var lines = text.split("\n");
  var out = [];
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    var trimmed = line.trim();
    if (!trimmed || trimmed.charAt(0) === "#") {
      out.push(line);
      continue;
    }
    var absoluteUrl = new URL(trimmed, baseUrl).toString();
    var token = await encryptUrl(absoluteUrl, env);
    out.push("/hls/seg/" + token);
  }
  return out.join("\n");
}

async function handleSegment(env, url) {
  var state = await getState(env);
  if (!state.enabled) {
    return new Response("Sharing disabled", { status: 403, headers: CORS_HEADERS });
  }

  var token = url.pathname.substring("/hls/seg/".length);
  var realUrl;
  try {
    realUrl = await decryptUrl(token, env);
  } catch (e) {
    return new Response("Bad segment token", { status: 400, headers: CORS_HEADERS });
  }

  var upstream = await fetch(realUrl);
  var headers = new Headers(upstream.headers);
  for (var key in CORS_HEADERS) headers.set(key, CORS_HEADERS[key]);
  headers.set("Cache-Control", "no-store");

  var contentType = upstream.headers.get("content-type") || "";
  var isSubManifest = realUrl.indexOf(".m3u8") !== -1 || contentType.indexOf("mpegurl") !== -1;

  if (isSubManifest) {
    var text = await upstream.text();
    var subBase = realUrl.substring(0, realUrl.lastIndexOf("/") + 1);
    var rewritten = await rewriteManifest(text, subBase, env);
    headers.set("Content-Type", "application/vnd.apple.mpegurl");
    return new Response(rewritten, { headers: headers });
  }

  return new Response(upstream.body, { status: upstream.status, headers: headers });
}

/* --- Chiffrement AES-GCM sans état (pas de KV par segment) --- */

async function getCryptoKey(env) {
  var raw = base64ToBytes(env.ENC_KEY);
  return crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
}

function base64ToBytes(b64) {
  var bin = atob(b64);
  var bytes = new Uint8Array(bin.length);
  for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

function bytesToBase64Url(bytes) {
  var bin = "";
  for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function base64UrlToBytes(str) {
  str = str.replace(/-/g, "+").replace(/_/g, "/");
  while (str.length % 4) str += "=";
  return base64ToBytes(str);
}

async function encryptUrl(plainUrl, env) {
  var key = await getCryptoKey(env);
  var iv = crypto.getRandomValues(new Uint8Array(12));
  var enc = new TextEncoder().encode(plainUrl);
  var cipher = await crypto.subtle.encrypt({ name: "AES-GCM", iv: iv }, key, enc);
  var cipherBytes = new Uint8Array(cipher);
  var combined = new Uint8Array(iv.length + cipherBytes.length);
  combined.set(iv, 0);
  combined.set(cipherBytes, iv.length);
  return bytesToBase64Url(combined);
}

async function decryptUrl(token, env) {
  var key = await getCryptoKey(env);
  var combined = base64UrlToBytes(token);
  var iv = combined.slice(0, 12);
  var cipher = combined.slice(12);
  var plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: iv }, key, cipher);
  return new TextDecoder().decode(plain);
}
