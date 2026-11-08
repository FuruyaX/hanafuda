// 同じ Wi-Fi 内の端末同士を WebRTC で直接つなぐ、サーバーなしの通信層。
// 接続情報は「招待コード」「返信コード」としてコピー＆ペーストで交換する。
// ゲームの中身（Python）からは window.net を通して使う。
//
// ホスト: createInvite(seat) → 招待コード / acceptReply(seat, 返信コード)
// ゲスト: acceptInvite(招待コード) → {seat, code: 返信コード}
// 共通:   send(seat, text)（ゲストからホストへは seat = -1）, onmessage(seat, text), onstatus(seat, state)

const PREFIX = 'HF1.';
const HOST = -1;
// インターネットなしの LAN でつなぐため STUN/TURN は使わない（同一ネットワークのみ）
const RTC_CONFIG = { iceServers: [] };

const peers = new Map(); // seat -> { pc, ch }  （ゲスト側はホストを seat=-1 で持つ）

function b64urlEncode(bytes) {
  let s = '';
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function b64urlDecode(text) {
  const s = atob(text.replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(s, (c) => c.charCodeAt(0));
}

async function pipe(bytes, stream) {
  const out = new Blob([bytes]).stream().pipeThrough(stream);
  return new Uint8Array(await new Response(out).arrayBuffer());
}

async function encode(obj) {
  const raw = new TextEncoder().encode(JSON.stringify(obj));
  return PREFIX + b64urlEncode(await pipe(raw, new CompressionStream('deflate-raw')));
}

async function decode(code) {
  const text = code.replace(/\s+/g, '');
  if (!text.startsWith(PREFIX)) throw new Error('コードの形式が違います（HF1. で始まるコードを貼り付けてください）');
  const raw = await pipe(b64urlDecode(text.slice(PREFIX.length)), new DecompressionStream('deflate-raw'));
  return JSON.parse(new TextDecoder().decode(raw));
}

// 候補（接続先アドレス）が出そろうまで待つ。LAN だけなので数秒で打ち切る
function waitForIce(pc, ms = 4000) {
  if (pc.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      if (pc.iceGatheringState === 'complete') resolve();
    };
    pc.addEventListener('icegatheringstatechange', done);
    setTimeout(resolve, ms);
  });
}

function setupChannel(seat, ch) {
  ch.onopen = () => net.onstatus?.(seat, 'open');
  ch.onclose = () => net.onstatus?.(seat, 'closed');
  ch.onmessage = (e) => net.onmessage?.(seat, e.data);
}

function watchConnection(seat, pc) {
  pc.onconnectionstatechange = () => {
    if (['failed', 'disconnected', 'closed'].includes(pc.connectionState)) {
      net.onstatus?.(seat, pc.connectionState);
    }
  };
}

const net = {
  onmessage: null,
  onstatus: null,

  async createInvite(seat) {
    net.close(seat);
    const pc = new RTCPeerConnection(RTC_CONFIG);
    const ch = pc.createDataChannel('game', { ordered: true });
    setupChannel(seat, ch);
    watchConnection(seat, pc);
    peers.set(seat, { pc, ch });
    await pc.setLocalDescription(await pc.createOffer());
    await waitForIce(pc);
    return encode({ t: 'o', seat, sdp: pc.localDescription.sdp });
  },

  async acceptReply(seat, code) {
    const d = await decode(code);
    if (d.t !== 'a') throw new Error('返信コードではありません（ゲストが作った返信コードを貼り付けてください）');
    const peer = peers.get(seat);
    if (!peer) throw new Error('先に招待コードを作ってください');
    await peer.pc.setRemoteDescription({ type: 'answer', sdp: d.sdp });
  },

  async acceptInvite(code) {
    const d = await decode(code);
    if (d.t !== 'o') throw new Error('招待コードではありません（ホストが作った招待コードを貼り付けてください）');
    net.close(HOST);
    const pc = new RTCPeerConnection(RTC_CONFIG);
    watchConnection(HOST, pc);
    pc.ondatachannel = (e) => {
      peers.set(HOST, { pc, ch: e.channel });
      setupChannel(HOST, e.channel);
    };
    peers.set(HOST, { pc, ch: null });
    await pc.setRemoteDescription({ type: 'offer', sdp: d.sdp });
    await pc.setLocalDescription(await pc.createAnswer());
    await waitForIce(pc);
    return { seat: d.seat, code: await encode({ t: 'a', sdp: pc.localDescription.sdp }) };
  },

  send(seat, text) {
    const ch = peers.get(seat)?.ch;
    if (ch && ch.readyState === 'open') ch.send(text);
  },

  isOpen(seat) {
    return peers.get(seat)?.ch?.readyState === 'open';
  },

  close(seat) {
    const peer = peers.get(seat);
    if (!peer) return;
    peer.ch?.close();
    peer.pc.close();
    peers.delete(seat);
  },

  closeAll() {
    for (const seat of [...peers.keys()]) net.close(seat);
  },

  async copy(text) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      return false;
    }
  },

  async share(text) {
    if (!navigator.share) return false;
    try {
      await navigator.share({ text });
      return true;
    } catch {
      return false;
    }
  },

  // 同じ画面の中でホストとゲストをつないで、コードの作成と通信を確かめる（?nettest）
  async selfTest() {
    const log = (m) => console.log('[nettest] ' + m);
    log('createInvite');
    const invite = await net.createInvite(1);
    log('acceptInvite ' + invite.length);
    const reply = await net.acceptInvite(invite);
    log('acceptReply ' + reply.code.length);
    await net.acceptReply(1, reply.code);
    log('waiting for channel');
    const got = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('timeout')), 10000);
      net.onmessage = (seat, text) => {
        clearTimeout(timer);
        resolve(`${seat}:${text}`);
      };
      const trySend = () => (net.isOpen(1) ? net.send(1, 'hello') : setTimeout(trySend, 100));
      trySend();
    });
    net.closeAll();
    return { inviteLength: invite.length, replyLength: reply.code.length, received: got };
  },
};

window.net = net;
