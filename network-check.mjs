// Probe the official endpoint with the pinned DSH transport, without credentials or model calls.
import { installProxyFromEnvironment, proxyRouteFor } from '@deepseek-ai/dsh-http-proxy';
import { pathToFileURL } from 'node:url';

export async function checkNetwork(url = 'https://api.deepseek.com/anthropic/v1/messages', timeoutMs = 10000) {
  const result = { type: 'network-check', reachable: false, credential_sent: false, paid_model_tasks: 0 };
  let dispose;
  try {
    dispose = await installProxyFromEnvironment({
      get: name => process.env[name] === undefined ? undefined : { value: process.env[name] },
    }, () => { throw new Error('INVALID_PROXY'); });
    result.proxy_used = proxyRouteFor(new URL(url)).proxied;
    const response = await fetch(url, { method: 'HEAD', redirect: 'error', signal: AbortSignal.timeout(timeoutMs) });
    result.reachable = true;
    result.http_status = response.status;
    await response.body?.cancel();
  } catch (error) {
    const code = error.cause?.code ?? error.code ?? error.name;
    result.error_code = /^[a-zA-Z0-9_]{1,80}$/.test(code) ? code : 'NETWORK_ERROR';
  } finally {
    if (dispose) await dispose();
  }
  return result;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const result = await checkNetwork();
  console.log(JSON.stringify(result));
  process.exitCode = result.reachable ? 0 : 2;
}
