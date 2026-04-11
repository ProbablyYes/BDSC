"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useAuth } from "../hooks/useAuth";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");
const WS_BASE = API.replace(/^http/, "ws");

/* ── Types ── */
type Room = {
  room_id: string; type: string; name: string; members: string[];
  admin_ids: string[]; team_id?: string; project_id?: string;
  last_message_preview: string; last_message_at: string; created_at: string;
};
type Msg = {
  msg_id: string; room_id: string; sender_id: string; sender_name: string;
  type: string; content: string; mentions: string[]; reply_to?: string;
  file_meta?: { filename: string; url: string; size: number; content_type: string };
  reactions: Record<string, string[]>; created_at: string;
};
type Contact = { user_id: string; display_name: string; role: string; source: string; team_name?: string };
type TeamInfo = { team_id: string; team_name: string; members: { user_id: string; display_name: string; role: string }[] };
type CtxMenu = { x: number; y: number; msg: Msg } | null;
type AIEntry = { id: string; query: string; reply: string; time: string; mode?: string; sender?: string };

const EMOJI_FULL = ["👍","❤️","😂","🎉","🤔","👏","🔥","💡","✅","❌","😊","🙏","💪","⭐","🚀","👀"];
const EMOJI_QUICK = ["👍","❤️","😂","🎉","🤔","👏"];

const AI_PROMPTS = [
  "@小文 帮我分析一下这个项目的优势和风险",
  "@小文 我该如何做竞品分析？",
  "@小文 给我一些商业模式建议",
  "@小文 帮我梳理项目的核心卖点",
];

/* ── Helpers ── */
function fmtTime(iso: string) {
  try { return new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }); } catch { return ""; }
}
function fmtDate(iso: string) {
  try {
    const d = new Date(iso); const now = new Date();
    if (d.toDateString() === now.toDateString()) return "今天";
    const y = new Date(now); y.setDate(y.getDate() - 1);
    if (d.toDateString() === y.toDateString()) return "昨天";
    return `${d.getMonth() + 1}月${d.getDate()}日`;
  } catch { return ""; }
}
function avatarColor(id: string) {
  const colors = ["#6B8AFF","#51cf66","#fcc419","#ff6b6b","#845ef7","#22b8cf","#ff922b","#e64980"];
  let h = 0; for (let i = 0; i < id.length; i++) h = id.charCodeAt(i) + ((h << 5) - h);
  return colors[Math.abs(h) % colors.length];
}
function fmtDuration(sec: number) {
  const m = Math.floor(sec / 60); const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/* ── SVG Icons ── */
const ICN = {
  back: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5M12 19l-7-7 7-7"/></svg>,
  plus: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 5v14M5 12h14"/></svg>,
  search: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>,
  send: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>,
  attach: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>,
  smile: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" y1="9" x2="9.01" y2="9"/><line x1="15" y1="9" x2="15.01" y2="9"/></svg>,
  video: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>,
  info: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>,
  file: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z"/><path d="M13 2v7h7"/></svg>,
  users: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/></svg>,
  user: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>,
  msg: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>,
  x: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12"/></svg>,
  phone: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.127.96.362 1.903.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.907.338 1.85.573 2.81.7A2 2 0 0122 16.92z"/></svg>,
  team: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>,
  copy: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>,
  reply: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 17 4 12 9 7"/><path d="M20 18v-2a4 4 0 00-4-4H4"/></svg>,
  forward: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="15 17 20 12 15 7"/><path d="M4 18v-2a4 4 0 014-4h12"/></svg>,
  trash: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>,
  check: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>,
  popout: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>,
  screen: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>,
  mic: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 1a3 3 0 00-3 3v8a3 3 0 006 0V4a3 3 0 00-3-3z"/><path d="M19 10v2a7 7 0 01-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/></svg>,
  micOff: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="1" y1="1" x2="23" y2="23"/><path d="M9 9v3a3 3 0 005.12 2.12M15 9.34V4a3 3 0 00-5.94-.6"/><path d="M17 16.95A7 7 0 015 12v-2m14 0v2c0 .76-.13 1.49-.35 2.17"/><line x1="12" y1="19" x2="12" y2="23"/></svg>,
  camOff: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="1" y1="1" x2="23" y2="23"/><path d="M21 21H3a2 2 0 01-2-2V8a2 2 0 012-2h3"/><path d="M21 15V5a2 2 0 00-2-2H9"/></svg>,
  spark: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12 2L9 12l-7 1 5.5 5-1.5 7L12 20l6 5-1.5-7L22 13l-7-1z"/></svg>,
  down: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polyline points="6 9 12 15 18 9"/></svg>,
};

export default function ChatPage() {
  const user = useAuth();
  const [sideTab, setSideTab] = useState<"chats" | "contacts">("chats");
  const [rooms, setRooms] = useState<Room[]>([]);
  const [activeRoom, setActiveRoom] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [searchTxt, setSearchTxt] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [newRoomName, setNewRoomName] = useState("");
  const [newRoomMembers, setNewRoomMembers] = useState<string[]>([]);
  const [showEmoji, setShowEmoji] = useState(false);
  const [showInfo, setShowInfo] = useState(false);
  const [roomFiles, setRoomFiles] = useState<Msg[]>([]);
  const [typingUsers, setTypingUsers] = useState<string[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [teams, setTeams] = useState<TeamInfo[]>([]);
  const [replyTo, setReplyTo] = useState<Msg | null>(null);
  const [hoverMsg, setHoverMsg] = useState("");
  const [infoTab, setInfoTab] = useState<"members" | "files">("members");

  /* P1: Context menu + multi-select + forward */
  const [ctxMenu, setCtxMenu] = useState<CtxMenu>(null);
  const [multiSelect, setMultiSelect] = useState(false);
  const [selectedMsgs, setSelectedMsgs] = useState<Set<string>>(new Set());
  const [forwardTarget, setForwardTarget] = useState<string | null>(null);

  /* P2: AI Panel */
  const [showAI, setShowAI] = useState(false);
  const [aiEntries, setAiEntries] = useState<AIEntry[]>([]);
  const [aiThinking, setAiThinking] = useState(false);
  const [aiFollowUp, setAiFollowUp] = useState("");
  const [aiPanelW, setAiPanelW] = useState(380);
  const [draggingAI, setDraggingAI] = useState(false);
  const [aiTab, setAiTab] = useState<"chat" | "files">("chat");
  const [aiSearch, setAiSearch] = useState("");
  const [fileSearch, setFileSearch] = useState("");
  const aiPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* P3: Sidebar resize */
  const [sideW, setSideW] = useState(310);
  const [draggingSide, setDraggingSide] = useState(false);

  /* P3: Split view */
  const [splitRoom, setSplitRoom] = useState("");
  const [splitMessages, setSplitMessages] = useState<Msg[]>([]);

  /* P4: Video call */
  const [videoActive, setVideoActive] = useState(false);
  const [incomingCall, setIncomingCall] = useState<{ from_user: string; from_name: string; sdp: RTCSessionDescriptionInit } | null>(null);
  const [videoFloat, setVideoFloat] = useState(false);
  const [muted, setMuted] = useState(false);
  const [camOff, setCamOff] = useState(false);
  const [callTimer, setCallTimer] = useState(0);
  const [screenSharing, setScreenSharing] = useState(false);
  const localVideoRef = useRef<HTMLVideoElement>(null);
  const remoteVideoRef = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const screenStreamRef = useRef<MediaStream | null>(null);
  const callTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const ringtoneRef = useRef<{ ctx: AudioContext; osc: OscillatorNode; gain: GainNode } | null>(null);

  /* New message indicator */
  const [showNewMsgBtn, setShowNewMsgBtn] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const msgEndRef = useRef<HTMLDivElement>(null);
  const msgContainerRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const typingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const videoDragRef = useRef<{ startX: number; startY: number; x: number; y: number }>({ startX: 0, startY: 0, x: 0, y: 0 });
  const [videoPos, setVideoPos] = useState({ x: 0, y: 0 });

  const uid = user?.user_id || "";
  const uname = user?.display_name || "";

  /* ── Loaders ── */
  const loadRooms = useCallback(async () => {
    if (!uid) return;
    try { const r = await fetch(`${API}/api/chat/rooms?user_id=${uid}`); const d = await r.json(); setRooms(d.rooms || []); } catch {}
  }, [uid]);

  const loadContacts = useCallback(async () => {
    if (!uid) return;
    try {
      const r = await fetch(`${API}/api/chat/contacts?user_id=${uid}`);
      const d = await r.json();
      setContacts(d.contacts || []);
      setTeams(d.teams || []);
    } catch {}
  }, [uid]);

  useEffect(() => { loadRooms(); loadContacts(); }, [loadRooms, loadContacts]);

  const loadMessages = useCallback(async (roomId: string) => {
    try { const r = await fetch(`${API}/api/chat/rooms/${roomId}/messages?limit=200`); const d = await r.json(); setMessages(d.messages || []); } catch {}
  }, []);

  /* ── WebSocket with auto-reconnect ── */
  useEffect(() => {
    if (!activeRoom || !uid) return;
    loadMessages(activeRoom);
    let dead = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let retryDelay = 1000;

    function connect() {
      if (dead) return;
      const ws = new WebSocket(`${WS_BASE}/ws/chat/${activeRoom}?user_id=${uid}&user_name=${encodeURIComponent(uname)}`);
      wsRef.current = ws;

      ws.onopen = () => { retryDelay = 1000; };

      ws.onmessage = (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.type === "new_message") {
            const newMsg = data.message as Msg;
            setMessages(prev => prev.some(m => m.msg_id === newMsg.msg_id) ? prev : [...prev, newMsg]);
            loadRooms();
            if (newMsg.sender_id === "ai_xiaowen" && newMsg.type === "ai_reply") {
              setAiThinking(false);
              setShowAI(true);
            }
          } else if (data.type === "ai_analysis") {
            const entry = data.entry as AIEntry;
            setAiEntries(prev => prev.some(e => e.id === entry.id) ? prev : [...prev, entry]);
            setShowAI(true);
          } else if (data.type === "reaction_update") {
            setMessages(prev => prev.map(m => m.msg_id === data.msg_id ? { ...m, reactions: data.reactions } : m));
          } else if (data.type === "typing") {
            setTypingUsers(prev => prev.includes(data.user_name) ? prev : [...prev, data.user_name]);
            setTimeout(() => setTypingUsers(prev => prev.filter(n => n !== data.user_name)), 3000);
          } else if (data.type === "video_offer") {
            setIncomingCall({ from_user: data.from_user, from_name: data.from_name, sdp: data.sdp });
          } else if (data.type === "video_answer" && pcRef.current) {
            pcRef.current.setRemoteDescription(new RTCSessionDescription(data.sdp));
          } else if (data.type === "ice_candidate" && pcRef.current) {
            pcRef.current.addIceCandidate(new RTCIceCandidate(data.candidate));
          } else if (data.type === "video_hang_up") { endCall(); }
        } catch {}
      };

      ws.onclose = () => {
        if (dead) return;
        wsRef.current = null;
        reconnectTimer = setTimeout(() => { retryDelay = Math.min(retryDelay * 2, 8000); connect(); }, retryDelay);
      };

      ws.onerror = () => { try { ws.close(); } catch {} };
    }

    connect();
    return () => { dead = true; if (reconnectTimer) clearTimeout(reconnectTimer); wsRef.current?.close(); wsRef.current = null; };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeRoom, uid, uname]);

  /* Load AI analysis history when switching rooms */
  useEffect(() => {
    if (!activeRoom) { setAiEntries([]); return; }
    setAiEntries([]);
    (async () => {
      try {
        const r = await fetch(`${API}/api/chat/rooms/${activeRoom}/ai-history`);
        if (r.ok) {
          const d = await r.json();
          setAiEntries(d.entries || []);
        }
      } catch {}
    })();
  }, [activeRoom]);

  /* Auto-poll for AI replies while thinking — handles cases where WS broadcast fails */
  useEffect(() => {
    if (!aiThinking || !activeRoom) {
      if (aiPollRef.current) { clearInterval(aiPollRef.current); aiPollRef.current = null; }
      return;
    }
    let count = 0;
    aiPollRef.current = setInterval(async () => {
      count++;
      try {
        const [msgR, aiR] = await Promise.all([
          fetch(`${API}/api/chat/rooms/${activeRoom}/messages?limit=200`),
          fetch(`${API}/api/chat/rooms/${activeRoom}/ai-history`),
        ]);
        if (msgR.ok) { const d = await msgR.json(); setMessages(d.messages || []); }
        if (aiR.ok) {
          const d = await aiR.json();
          const entries = d.entries || [];
          setAiEntries(entries);
          if (entries.length > 0) {
            const latest = entries[entries.length - 1];
            if (latest.reply && latest.reply.length > 0) {
              setAiThinking(false);
              setShowAI(true);
            }
          }
        }
      } catch {}
      if (count >= 30) setAiThinking(false);
    }, 3000);
    return () => { if (aiPollRef.current) { clearInterval(aiPollRef.current); aiPollRef.current = null; } };
  }, [aiThinking, activeRoom]);

  /* Ringtone for incoming calls */
  useEffect(() => {
    if (incomingCall && !videoActive) {
      try {
        const ctx = new AudioContext();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "sine";
        osc.frequency.value = 440;
        gain.gain.value = 0.15;
        osc.connect(gain).connect(ctx.destination);
        osc.start();
        const id = setInterval(() => {
          osc.frequency.value = osc.frequency.value === 440 ? 520 : 440;
        }, 500);
        ringtoneRef.current = { ctx, osc, gain };
        return () => {
          clearInterval(id);
          try { osc.stop(); ctx.close(); } catch {}
          ringtoneRef.current = null;
        };
      } catch {}
    } else if (ringtoneRef.current) {
      try { ringtoneRef.current.osc.stop(); ringtoneRef.current.ctx.close(); } catch {}
      ringtoneRef.current = null;
    }
  }, [incomingCall, videoActive]);

  /* Auto-scroll + new message indicator */
  useEffect(() => {
    const container = msgContainerRef.current;
    if (!container) return;
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 100;
    if (atBottom) {
      msgEndRef.current?.scrollIntoView({ behavior: "smooth" });
      setShowNewMsgBtn(false);
    } else if (messages.length > 0) {
      setShowNewMsgBtn(true);
    }
  }, [messages]);

  const scrollToBottom = () => {
    msgEndRef.current?.scrollIntoView({ behavior: "smooth" });
    setShowNewMsgBtn(false);
  };

  /* Handle scroll for new-msg indicator */
  const handleMsgScroll = () => {
    const c = msgContainerRef.current;
    if (!c) return;
    if (c.scrollHeight - c.scrollTop - c.clientHeight < 60) setShowNewMsgBtn(false);
  };

  /* Close context menu on click elsewhere */
  useEffect(() => {
    if (!ctxMenu) return;
    const close = () => setCtxMenu(null);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [ctxMenu]);

  /* P3: Sidebar resize drag */
  useEffect(() => {
    if (!draggingSide) return;
    const onMove = (e: MouseEvent) => { setSideW(Math.max(220, Math.min(500, e.clientX))); };
    const onUp = () => setDraggingSide(false);
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => { document.removeEventListener("mousemove", onMove); document.removeEventListener("mouseup", onUp); };
  }, [draggingSide]);

  /* AI panel resize drag */
  useEffect(() => {
    if (!draggingAI) return;
    const onMove = (e: MouseEvent) => { setAiPanelW(Math.max(300, Math.min(700, window.innerWidth - e.clientX))); };
    const onUp = () => setDraggingAI(false);
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => { document.removeEventListener("mousemove", onMove); document.removeEventListener("mouseup", onUp); };
  }, [draggingAI]);

  /* ── Send ── */
  const sendTyping = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: "typing" }));
  };

  const sendMessage = () => {
    const text = input.trim();
    if (!text || !activeRoom) return;
    const mentions: string[] = [];
    const currentRoom = rooms.find(r => r.room_id === activeRoom);
    const roomHasAI = currentRoom?.members.includes("ai_xiaowen");
    if (text.includes("@小文") || roomHasAI) { mentions.push("ai_xiaowen"); setAiThinking(true); }
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "text", content: text, mentions, reply_to: replyTo?.msg_id || null }));
    } else {
      fetch(`${API}/api/chat/rooms/${activeRoom}/messages`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sender_id: uid, sender_name: uname, msg_type: "text", content: text, mentions, reply_to: replyTo?.msg_id || null }),
      }).then(r => r.json()).then(d => {
        if (d.message) setMessages(prev => [...prev, d.message]);
        if (roomHasAI) {
          const poll = (n: number) => {
            if (n <= 0) { setAiThinking(false); return; }
            setTimeout(() => {
              loadMessages(activeRoom);
              fetch(`${API}/api/chat/rooms/${activeRoom}/ai-history`).then(r => r.json()).then(h => setAiEntries(h.entries || [])).catch(() => {});
              poll(n - 1);
            }, 3000);
          };
          poll(10);
        }
      });
    }
    setInput(""); setReplyTo(null); setShowEmoji(false);
    inputRef.current?.focus();
  };

  /* P2: AI follow-up from panel */
  const sendAIFollowUp = () => {
    const text = aiFollowUp.trim();
    if (!text || !activeRoom) return;
    const full = `@小文 ${text}`;
    setAiThinking(true);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "text", content: full, mentions: ["ai_xiaowen"] }));
    }
    setAiFollowUp("");
  };

  const deleteAiEntry = async (entryId: string) => {
    if (!activeRoom) return;
    try {
      await fetch(`${API}/api/chat/rooms/${activeRoom}/ai-history/${entryId}`, { method: "DELETE" });
      setAiEntries(prev => prev.filter(e => e.id !== entryId));
    } catch {}
  };

  /* ── Create room ── */
  const createRoom = async (name: string, members: string[], type = "group") => {
    try {
      const r = await fetch(`${API}/api/chat/rooms`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, room_type: type, members: [uid, ...members], admin_ids: [uid] }),
      });
      const d = await r.json();
      if (d.room) {
        await loadRooms();
        setActiveRoom(d.room.room_id);
        setShowCreate(false); setNewRoomName(""); setNewRoomMembers([]);
        setSideTab("chats");
      }
    } catch (e) { console.error("create room error:", e); }
  };

  const startDM = async (contact: Contact) => {
    if (contact.user_id === "ai_xiaowen") {
      const existing = rooms.find(r => r.name === "小文 AI" && r.type === "direct");
      if (existing) { setActiveRoom(existing.room_id); setSideTab("chats"); return; }
      await createRoom("小文 AI", ["ai_xiaowen"], "direct");
      return;
    }
    const existing = rooms.find(r => r.type === "direct" && r.members.includes(contact.user_id) && r.members.includes(uid) && r.members.length === 2);
    if (existing) { setActiveRoom(existing.room_id); setSideTab("chats"); return; }
    await createRoom(contact.display_name, [contact.user_id], "direct");
  };

  const createTeamRoom = async (team: TeamInfo) => {
    const existing = rooms.find(r => r.type === "team" && r.name === team.team_name);
    if (existing) { setActiveRoom(existing.room_id); setSideTab("chats"); return; }
    const memberIds = team.members.map(m => m.user_id).filter(id => id !== uid);
    await createRoom(team.team_name, memberIds, "team");
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !activeRoom) return;
    const fd = new FormData(); fd.append("file", file); fd.append("sender_id", uid); fd.append("sender_name", uname);
    try { const r = await fetch(`${API}/api/chat/rooms/${activeRoom}/files`, { method: "POST", body: fd }); const d = await r.json(); if (d.message) setMessages(prev => [...prev, d.message]); } catch {}
    e.target.value = "";
  };

  const loadFiles = async () => {
    if (!activeRoom) return;
    try { const r = await fetch(`${API}/api/chat/rooms/${activeRoom}/files`); const d = await r.json(); setRoomFiles(d.files || []); } catch {}
  };

  const toggleReaction = (msgId: string, emoji: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: "reaction", msg_id: msgId, emoji }));
  };

  const deleteRoom = async (roomId: string) => {
    if (!confirm("确定删除此聊天室？")) return;
    await fetch(`${API}/api/chat/rooms/${roomId}`, { method: "DELETE" });
    if (activeRoom === roomId) { setActiveRoom(""); setMessages([]); }
    loadRooms();
  };

  /* P1: Context menu actions */
  const copyMsg = (text: string) => { navigator.clipboard.writeText(text).catch(() => {}); setCtxMenu(null); };
  const handleContextMenu = (e: React.MouseEvent, msg: Msg) => {
    e.preventDefault(); setCtxMenu({ x: e.clientX, y: e.clientY, msg });
  };
  const toggleMsgSelect = (id: string) => {
    setSelectedMsgs(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  };
  const forwardSelected = async () => {
    if (!forwardTarget || selectedMsgs.size === 0) return;
    const toForward = messages.filter(m => selectedMsgs.has(m.msg_id));
    const content = toForward.map(m => `[${m.sender_name}]: ${m.content}`).join("\n");
    await fetch(`${API}/api/chat/rooms/${forwardTarget}/messages`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sender_id: uid, sender_name: uname, msg_type: "text", content: `[转发消息]\n${content}` }),
    });
    setMultiSelect(false); setSelectedMsgs(new Set()); setForwardTarget(null);
  };

  /* Rebind video streams whenever videoFloat toggles or videoActive changes */
  useEffect(() => {
    if (!videoActive) return;
    const rebind = setTimeout(() => {
      if (localVideoRef.current && localStreamRef.current) {
        localVideoRef.current.srcObject = localStreamRef.current;
        localVideoRef.current.play().catch(() => {});
      }
      if (remoteVideoRef.current && pcRef.current) {
        const receivers = pcRef.current.getReceivers();
        const videoReceiver = receivers.find(r => r.track?.kind === "video");
        if (videoReceiver?.track) {
          remoteVideoRef.current.srcObject = new MediaStream([videoReceiver.track, ...receivers.filter(r => r.track?.kind === "audio").map(r => r.track!)]);
          remoteVideoRef.current.play().catch(() => {});
        }
      }
    }, 50);
    return () => clearTimeout(rebind);
  }, [videoActive, videoFloat]);

  /* ── Video ── */
  const startCall = async (targetUserId: string) => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      localStreamRef.current = stream;
      setVideoActive(true); setCallTimer(0);
      callTimerRef.current = setInterval(() => setCallTimer(t => t + 1), 1000);
      setTimeout(() => {
        if (localVideoRef.current) { localVideoRef.current.srcObject = stream; localVideoRef.current.play().catch(() => {}); }
      }, 100);
      const pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
      pcRef.current = pc;
      stream.getTracks().forEach(track => pc.addTrack(track, stream));
      pc.onicecandidate = (ev) => { if (ev.candidate && wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: "ice_candidate", target_user: targetUserId, candidate: ev.candidate })); };
      pc.ontrack = (ev) => { if (remoteVideoRef.current) { remoteVideoRef.current.srcObject = ev.streams[0]; remoteVideoRef.current.play().catch(() => {}); } };
      const offer = await pc.createOffer(); await pc.setLocalDescription(offer);
      if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: "video_offer", target_user: targetUserId, sdp: offer }));
    } catch (err) { console.error("call err:", err); }
  };

  const acceptCall = async () => {
    if (!incomingCall) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      localStreamRef.current = stream;
      setVideoActive(true); setCallTimer(0);
      callTimerRef.current = setInterval(() => setCallTimer(t => t + 1), 1000);
      setTimeout(() => {
        if (localVideoRef.current) { localVideoRef.current.srcObject = stream; localVideoRef.current.play().catch(() => {}); }
      }, 100);
      const pc = new RTCPeerConnection({ iceServers: [{ urls: "stun:stun.l.google.com:19302" }] });
      pcRef.current = pc;
      stream.getTracks().forEach(track => pc.addTrack(track, stream));
      pc.onicecandidate = (ev) => { if (ev.candidate && wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: "ice_candidate", target_user: incomingCall.from_user, candidate: ev.candidate })); };
      pc.ontrack = (ev) => { if (remoteVideoRef.current) { remoteVideoRef.current.srcObject = ev.streams[0]; remoteVideoRef.current.play().catch(() => {}); } };
      await pc.setRemoteDescription(new RTCSessionDescription(incomingCall.sdp));
      const answer = await pc.createAnswer(); await pc.setLocalDescription(answer);
      if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: "video_answer", target_user: incomingCall.from_user, sdp: answer }));
      setIncomingCall(null);
    } catch (err) { console.error("accept err:", err); }
  };

  const endCall = () => {
    pcRef.current?.close(); pcRef.current = null;
    localStreamRef.current?.getTracks().forEach(t => t.stop()); localStreamRef.current = null;
    screenStreamRef.current?.getTracks().forEach(t => t.stop()); screenStreamRef.current = null;
    if (localVideoRef.current) localVideoRef.current.srcObject = null;
    if (remoteVideoRef.current) remoteVideoRef.current.srcObject = null;
    setVideoActive(false); setIncomingCall(null); setVideoFloat(false);
    setMuted(false); setCamOff(false); setScreenSharing(false); setCallTimer(0);
    if (callTimerRef.current) clearInterval(callTimerRef.current);
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: "video_hang_up" }));
  };

  const toggleMute = () => {
    localStreamRef.current?.getAudioTracks().forEach(t => { t.enabled = muted; });
    setMuted(!muted);
  };

  const toggleCam = () => {
    localStreamRef.current?.getVideoTracks().forEach(t => { t.enabled = camOff; });
    setCamOff(!camOff);
  };

  const toggleScreenShare = async () => {
    if (screenSharing) {
      screenStreamRef.current?.getTracks().forEach(t => t.stop());
      const videoTrack = localStreamRef.current?.getVideoTracks()[0];
      if (videoTrack && pcRef.current) {
        const sender = pcRef.current.getSenders().find(s => s.track?.kind === "video");
        sender?.replaceTrack(videoTrack);
      }
      setScreenSharing(false);
      return;
    }
    try {
      const screen = await navigator.mediaDevices.getDisplayMedia({ video: true });
      screenStreamRef.current = screen;
      const screenTrack = screen.getVideoTracks()[0];
      if (pcRef.current) {
        const sender = pcRef.current.getSenders().find(s => s.track?.kind === "video");
        sender?.replaceTrack(screenTrack);
      }
      screenTrack.onended = () => { toggleScreenShare(); };
      setScreenSharing(true);
    } catch {}
  };

  /* P3: Pop-out chat */
  const popOutChat = () => {
    if (!activeRoom) return;
    window.open(`/chat/pop?room=${activeRoom}&user_id=${uid}&user_name=${encodeURIComponent(uname)}`, `chat_${activeRoom}`, "width=480,height=640,menubar=no,toolbar=no");
  };

  /* ── Derived ── */
  const currentRoom = rooms.find(r => r.room_id === activeRoom);
  const currentMembers = currentRoom?.members || [];
  const filteredRooms = searchTxt ? rooms.filter(r => r.name.toLowerCase().includes(searchTxt.toLowerCase())) : rooms;
  const teachers = contacts.filter(c => c.role === "teacher");
  const students = contacts.filter(c => c.role === "student" && c.source === "student");
  const teammates = contacts.filter(c => c.role !== "teacher" && c.role !== "ai" && c.source === "team");
  const aiContact = contacts.find(c => c.role === "ai");
  const isTeacher = user?.role === "teacher";

  const groupedMsgs: { date: string; msgs: Msg[] }[] = [];
  let lastDate = "";
  for (const m of messages) {
    const d = fmtDate(m.created_at);
    if (d !== lastDate) { groupedMsgs.push({ date: d, msgs: [] }); lastDate = d; }
    groupedMsgs[groupedMsgs.length - 1]?.msgs.push(m);
  }

  if (!user) return <div className="vc-loading">加载中...</div>;

  const Avatar = ({ id, name, size = 36 }: { id: string; name: string; size?: number }) => {
    if (id === "ai_xiaowen") return <img src="/xiaowen-avatar.png" alt="小文" style={{ width: size, height: size, borderRadius: "50%" }} />;
    return (
      <div style={{ width: size, height: size, borderRadius: "50%", background: avatarColor(id), display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 700, fontSize: size * 0.38, flexShrink: 0 }}>
        {(name?.[0] || "?").toUpperCase()}
      </div>
    );
  };

  /* ── Render a single message ── */
  const renderMsg = (m: Msg) => {
    const isOwn = m.sender_id === uid;
    const isAI = m.sender_id === "ai_xiaowen";
    const isSystem = m.type === "system";
    if (isSystem) return <div key={m.msg_id} className="vc-sys-msg">{m.content}</div>;
    const replyRef = m.reply_to ? messages.find(x => x.msg_id === m.reply_to) : null;
    const reactions = Object.entries(m.reactions || {});
    const isHover = hoverMsg === m.msg_id;
    const isSelected = selectedMsgs.has(m.msg_id);

    return (
      <div key={m.msg_id} className={`vc-msg${isOwn ? " own" : ""}${isAI ? " ai" : ""}`}
        onMouseEnter={() => setHoverMsg(m.msg_id)} onMouseLeave={() => setHoverMsg("")}
        onContextMenu={(e) => handleContextMenu(e, m)}>
        {multiSelect && (
          <label className="vc-msg-checkbox">
            <input type="checkbox" checked={isSelected} onChange={() => toggleMsgSelect(m.msg_id)} />
          </label>
        )}
        {!isOwn && <Avatar id={m.sender_id} name={m.sender_name} size={34} />}
        <div className="vc-msg-content">
          {!isOwn && <div className="vc-msg-sender">{isAI ? "小文 AI" : m.sender_name}</div>}
          {replyRef && (
            <div className="vc-msg-reply-ref" onClick={() => {
              const el = document.getElementById(`msg-${replyRef.msg_id}`);
              el?.scrollIntoView({ behavior: "smooth", block: "center" });
              el?.classList.add("vc-msg-highlight");
              setTimeout(() => el?.classList.remove("vc-msg-highlight"), 1500);
            }}>
              ↩ {replyRef.sender_name}: {replyRef.content?.slice(0, 50)}
            </div>
          )}
          {m.type === "image" && m.file_meta?.url ? (
            <img src={`${API}${m.file_meta.url}`} alt={m.file_meta.filename} className="vc-msg-image" />
          ) : m.type === "file" && m.file_meta?.url ? (
            <a href={`${API}${m.file_meta.url}`} target="_blank" rel="noreferrer" className="vc-msg-file-card">
              <span className="vc-file-icon">{ICN.file}</span>
              <div><div className="vc-file-name">{m.file_meta.filename}</div><div className="vc-file-size">{((m.file_meta.size || 0) / 1024).toFixed(1)} KB</div></div>
            </a>
          ) : isAI && m.type === "ai_reply" && m.content.length > 120 ? (
            <div className="vc-msg-bubble vc-ai-truncated">
              {m.content.slice(0, 120)}...
              <button className="vc-view-full" onClick={() => setShowAI(true)}>展开 AI 面板查看完整回复 →</button>
            </div>
          ) : (
            <div className="vc-msg-bubble">{m.content}</div>
          )}
          <div className="vc-msg-time">{fmtTime(m.created_at)}</div>
          {reactions.length > 0 && (
            <div className="vc-msg-reactions">
              {reactions.map(([emoji, users]) => (
                <button key={emoji} className={`vc-react-pill${(users as string[]).includes(uid) ? " own" : ""}`} onClick={() => toggleReaction(m.msg_id, emoji)}>{emoji} {(users as string[]).length}</button>
              ))}
            </div>
          )}
        </div>
        {isHover && !multiSelect && (
          <div className={`vc-msg-toolbar${isOwn ? " own" : ""}`}>
            <button onClick={() => setReplyTo(m)} title="回复">{ICN.reply}</button>
            {EMOJI_QUICK.map(em => <button key={em} onClick={() => toggleReaction(m.msg_id, em)}>{em}</button>)}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="vc-chat">
      {/* ══════ LEFT SIDEBAR ══════ */}
      <aside className="vc-sidebar" style={{ width: sideW, minWidth: sideW }}>
        <div className="vc-sidebar-top">
          <div className="vc-sidebar-header">
            <Link href={user.role === "teacher" ? "/teacher" : "/student"} className="vc-back">{ICN.back}</Link>
            <span className="vc-sidebar-title">消息</span>
            <button className="vc-icon-btn" onClick={() => setShowCreate(true)} title="发起群聊">{ICN.plus}</button>
          </div>
          <div className="vc-side-tabs">
            <button className={`vc-side-tab${sideTab === "chats" ? " active" : ""}`} onClick={() => setSideTab("chats")}>
              <span className="vc-tab-icon">{ICN.msg}</span>聊天
            </button>
            <button className={`vc-side-tab${sideTab === "contacts" ? " active" : ""}`} onClick={() => setSideTab("contacts")}>
              <span className="vc-tab-icon">{ICN.users}</span>联系人
            </button>
          </div>
          {sideTab === "chats" && (
            <div className="vc-search-wrap">
              <span className="vc-search-icon">{ICN.search}</span>
              <input className="vc-search" value={searchTxt} onChange={e => setSearchTxt(e.target.value)} placeholder="搜索聊天" />
            </div>
          )}
        </div>

        {sideTab === "chats" && (
          <div className="vc-room-list">
            {filteredRooms.map(r => (
              <div key={r.room_id} className={`vc-room${r.room_id === activeRoom ? " active" : ""}`} onClick={() => { setActiveRoom(r.room_id); setShowInfo(false); setShowAI(false); }}>
                <div className="vc-room-avatar-wrap">
                  {r.type === "direct" ? <Avatar id={r.members.find(m => m !== uid) || r.room_id} name={r.name} size={42} /> : <div className="vc-room-avatar-group">{ICN.users}</div>}
                </div>
                <div className="vc-room-body">
                  <div className="vc-room-top-row"><span className="vc-room-name">{r.name}</span><span className="vc-room-time">{r.last_message_at ? fmtTime(r.last_message_at) : ""}</span></div>
                  <div className="vc-room-preview">{r.last_message_preview || "暂无消息"}</div>
                </div>
              </div>
            ))}
            {filteredRooms.length === 0 && <div className="vc-empty-hint">{searchTxt ? "无匹配" : "暂无聊天"}<br /><button className="vc-link-btn" onClick={() => setSideTab("contacts")}>从联系人开始</button></div>}
          </div>
        )}

        {sideTab === "contacts" && (
          <div className="vc-contacts-list">
            {aiContact && (
              <div className="vc-contact-section">
                <div className="vc-section-label">AI 助手</div>
                <div className="vc-contact-row" onClick={() => startDM(aiContact)}>
                  <Avatar id="ai_xiaowen" name="小文" size={38} />
                  <div className="vc-contact-info"><span className="vc-contact-name">小文 AI</span><span className="vc-contact-role">智能创业教练</span></div>
                </div>
              </div>
            )}
            {teams.length > 0 && (
              <div className="vc-contact-section">
                <div className="vc-section-label">我的团队</div>
                {teams.map(t => (
                  <div key={t.team_id} className="vc-contact-row" onClick={() => createTeamRoom(t)}>
                    <div className="vc-room-avatar-group small">{ICN.team}</div>
                    <div className="vc-contact-info"><span className="vc-contact-name">{t.team_name}</span><span className="vc-contact-role">{t.members.length} 人</span></div>
                  </div>
                ))}
              </div>
            )}
            {teachers.length > 0 && (
              <div className="vc-contact-section">
                <div className="vc-section-label">老师</div>
                {teachers.map(c => (
                  <div key={c.user_id} className="vc-contact-row" onClick={() => startDM(c)}>
                    <Avatar id={c.user_id} name={c.display_name} size={38} />
                    <div className="vc-contact-info"><span className="vc-contact-name">{c.display_name}</span><span className="vc-contact-role">教师</span></div>
                  </div>
                ))}
              </div>
            )}
            {teammates.length > 0 && (
              <div className="vc-contact-section">
                <div className="vc-section-label">队友</div>
                {teammates.map(c => (
                  <div key={c.user_id} className="vc-contact-row" onClick={() => startDM(c)}>
                    <Avatar id={c.user_id} name={c.display_name} size={38} />
                    <div className="vc-contact-info"><span className="vc-contact-name">{c.display_name}</span><span className="vc-contact-role">{c.team_name || "队员"}</span></div>
                  </div>
                ))}
              </div>
            )}
            {isTeacher && students.length > 0 && (
              <div className="vc-contact-section">
                <div className="vc-section-label">学生 ({students.length})</div>
                {students.map(c => (
                  <div key={c.user_id} className="vc-contact-row" onClick={() => startDM(c)}>
                    <Avatar id={c.user_id} name={c.display_name} size={38} />
                    <div className="vc-contact-info"><span className="vc-contact-name">{c.display_name}</span><span className="vc-contact-role">学生</span></div>
                  </div>
                ))}
              </div>
            )}
            {contacts.length === 0 && <div className="vc-empty-hint">暂无联系人<br />加入团队后自动获取</div>}
          </div>
        )}
      </aside>

      {/* P3: Resize handle */}
      <div className={`vc-resize-handle${draggingSide ? " dragging" : ""}`} onMouseDown={() => setDraggingSide(true)} />

      {/* ══════ MAIN ══════ */}
      <main className="vc-main">
        {!activeRoom ? (
          <div className="vc-welcome">
            <div className="vc-welcome-icon">{ICN.msg}</div>
            <h2>VentureCheck 聊天室</h2>
            <p>选择联系人或聊天室开始对话</p>
            <p className="vc-welcome-sub">输入 <strong>@小文</strong> 随时呼唤 AI 助手</p>
          </div>
        ) : (
          <div className={`vc-chat-area${splitRoom ? " split" : ""}`}>
            {/* ── Header ── */}
            <header className="vc-chat-header">
              <div className="vc-chat-header-left">
                {currentRoom?.type === "direct" ? <Avatar id={currentMembers.find(m => m !== uid) || ""} name={currentRoom?.name || ""} size={34} /> : <div className="vc-room-avatar-group small">{ICN.users}</div>}
                <div><h3>{currentRoom?.name || "聊天"}</h3><span className="vc-member-count">{currentMembers.length} 位成员</span></div>
              </div>
              <div className="vc-chat-header-actions">
                <button className="vc-icon-btn" onClick={() => { const o = currentMembers.filter(m => m !== uid); if (o[0]) startCall(o[0]); }} title="视频通话">{ICN.video}</button>
                <button className="vc-icon-btn" onClick={() => fileInputRef.current?.click()} title="发送文件">{ICN.attach}</button>
                <button className="vc-icon-btn" onClick={popOutChat} title="弹出窗口">{ICN.popout}</button>
                <button className={`vc-icon-btn${showAI ? " active" : ""}`} onClick={() => { setShowAI(v => !v); setShowInfo(false); }} title="AI 助手">{ICN.spark}</button>
                <button className={`vc-icon-btn${showInfo ? " active" : ""}`} onClick={() => { setShowInfo(v => !v); setShowAI(false); if (!showInfo) loadFiles(); }} title="聊天信息">{ICN.info}</button>
              </div>
            </header>

            {/* ── Incoming call overlay ── */}
            {incomingCall && !videoActive && (
              <div className="vc-call-overlay">
                <div className="vc-call-card">
                  <div className="vc-call-pulse" />
                  <div className="vc-call-pulse delay" />
                  <Avatar id={incomingCall.from_user} name={incomingCall.from_name} size={72} />
                  <h3 className="vc-call-name">{incomingCall.from_name}</h3>
                  <p className="vc-call-subtitle">邀请你视频通话...</p>
                  <div className="vc-call-actions">
                    <button className="vc-call-accept" onClick={acceptCall}>{ICN.phone} 接听</button>
                    <button className="vc-call-reject" onClick={() => setIncomingCall(null)}>{ICN.x} 拒绝</button>
                  </div>
                </div>
              </div>
            )}

            {/* ── Video (embedded or float) ── */}
            {videoActive && !videoFloat && (
              <div className="vc-video-bar">
                <div className="vc-video-area">
                  <video ref={remoteVideoRef} autoPlay playsInline className="vc-video-main" />
                  <video ref={localVideoRef} autoPlay playsInline muted className="vc-video-pip" />
                </div>
                <div className="vc-video-controls">
                  <span className="vc-video-timer">{fmtDuration(callTimer)}</span>
                  <button className={`vc-vc-btn${muted ? " active" : ""}`} onClick={toggleMute} title={muted ? "取消静音" : "静音"}>{muted ? ICN.micOff : ICN.mic}</button>
                  <button className={`vc-vc-btn${camOff ? " active" : ""}`} onClick={toggleCam} title={camOff ? "打开摄像头" : "关闭摄像头"}>{camOff ? ICN.camOff : ICN.video}</button>
                  <button className={`vc-vc-btn${screenSharing ? " active" : ""}`} onClick={toggleScreenShare} title="屏幕共享">{ICN.screen}</button>
                  <button className="vc-vc-btn" onClick={() => setVideoFloat(true)} title="悬浮窗">{ICN.popout}</button>
                  <button className="vc-vc-btn danger" onClick={endCall} title="挂断">{ICN.phone}</button>
                </div>
              </div>
            )}

            {/* ── Messages ── */}
            <div className="vc-messages" ref={msgContainerRef} onScroll={handleMsgScroll}>
              {groupedMsgs.map((g, gi) => (
                <div key={gi}>
                  <div className="vc-date-sep"><span>{g.date}</span></div>
                  {g.msgs.map(m => <div key={m.msg_id} id={`msg-${m.msg_id}`}>{renderMsg(m)}</div>)}
                </div>
              ))}
              <div ref={msgEndRef} />
            </div>

            {showNewMsgBtn && (
              <button className="vc-new-msg-indicator" onClick={scrollToBottom}>{ICN.down} 新消息</button>
            )}

            {typingUsers.length > 0 && <div className="vc-typing">{typingUsers.join("、")} 正在输入...</div>}

            {/* P1: Multi-select bar */}
            {multiSelect && (
              <div className="vc-multiselect-bar">
                <span>已选 {selectedMsgs.size} 条</span>
                <button onClick={() => setForwardTarget("pick")} disabled={selectedMsgs.size === 0}>{ICN.forward} 转发</button>
                <button onClick={() => { setMultiSelect(false); setSelectedMsgs(new Set()); }}>{ICN.x} 取消</button>
              </div>
            )}

            {replyTo && (
              <div className="vc-reply-bar">
                <span>回复 <strong>{replyTo.sender_name}</strong>: {replyTo.content?.slice(0, 60)}</span>
                <button onClick={() => setReplyTo(null)}>{ICN.x}</button>
              </div>
            )}

            {messages.length <= 2 && (
              <div className="vc-ai-hints">
                <div className="vc-ai-hints-head">
                  <img src="/xiaowen-avatar.png" alt="小文" className="vc-ai-hints-avatar" />
                  <span>小文 AI 可以帮你</span>
                </div>
                <div className="vc-ai-hints-list">
                  {AI_PROMPTS.map((p, i) => <button key={i} className="vc-ai-hint-btn" onClick={() => { setInput(p); inputRef.current?.focus(); }}>{p.replace("@小文 ", "")}</button>)}
                </div>
              </div>
            )}

            {/* ── Input ── */}
            <div className="vc-input-area">
              <div className="vc-input-tools">
                <button className={`vc-tool-btn${showEmoji ? " active" : ""}`} onClick={() => setShowEmoji(v => !v)}>{ICN.smile}</button>
                <button className="vc-tool-btn" onClick={() => fileInputRef.current?.click()}>{ICN.attach}</button>
                <button className="vc-tool-btn vc-at-btn" onClick={() => { setInput(prev => prev + "@小文 "); inputRef.current?.focus(); }}>@</button>
              </div>
              <div className="vc-input-row">
                <textarea
                  ref={inputRef} className="vc-textarea" value={input}
                  onChange={e => { setInput(e.target.value); if (typingTimer.current) clearTimeout(typingTimer.current); typingTimer.current = setTimeout(sendTyping, 400); }}
                  placeholder="输入消息，Enter 发送"
                  rows={1}
                  onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } }}
                  onInput={e => { const el = e.currentTarget; el.style.height = "auto"; el.style.height = Math.min(el.scrollHeight, 120) + "px"; }}
                />
                <button className="vc-send-btn" onClick={sendMessage} disabled={!input.trim()}>{ICN.send}</button>
              </div>
            </div>

            {showEmoji && (
              <div className="vc-emoji-panel">
                {EMOJI_FULL.map(em => <button key={em} className="vc-emoji-btn" onClick={() => { setInput(prev => prev + em); setShowEmoji(false); inputRef.current?.focus(); }}>{em}</button>)}
              </div>
            )}
            <input type="file" ref={fileInputRef} style={{ display: "none" }} onChange={handleFileUpload} />
          </div>
        )}

        {/* ══════ AI PANEL (P2) ══════ */}
        {showAI && activeRoom && (() => {
          const kw = aiSearch.trim().toLowerCase();
          const filteredEntries = kw
            ? aiEntries.filter(e => e.query.toLowerCase().includes(kw) || e.reply.toLowerCase().includes(kw) || (e.sender || "").toLowerCase().includes(kw))
            : aiEntries;
          const fkw = fileSearch.trim().toLowerCase();
          const filteredFiles = fkw
            ? roomFiles.filter(f => (f.file_meta?.filename || "").toLowerCase().includes(fkw) || (f.sender_name || "").toLowerCase().includes(fkw))
            : roomFiles;

          return (
          <>
          <div className={`vc-resize-handle ai${draggingAI ? " dragging" : ""}`} onMouseDown={() => setDraggingAI(true)} />
          <div className="vc-ai-panel" style={{ width: aiPanelW, minWidth: 300 }}>
            <div className="vc-ai-panel-header">
              <img src="/xiaowen-avatar.png" alt="小文" style={{ width: 32, height: 32, borderRadius: "50%" }} />
              <div style={{ flex: 1 }}>
                <strong>小文 AI 助手</strong>
                <div style={{ fontSize: 11, color: "var(--text-muted)" }}>群组共享面板 · 所有成员可见 · 共 {aiEntries.length} 条分析</div>
              </div>
              <button className="vc-icon-btn" onClick={() => setShowAI(false)}>{ICN.x}</button>
            </div>

            <div className="vc-ai-tabs">
              <button className={`vc-ai-tab${aiTab === "chat" ? " active" : ""}`} onClick={() => setAiTab("chat")}>{ICN.spark} 对话分析</button>
              <button className={`vc-ai-tab${aiTab === "files" ? " active" : ""}`} onClick={() => { setAiTab("files"); loadFiles(); }}>{ICN.file} 文件管理</button>
            </div>

            {aiTab === "chat" ? (
              <>
              {/* search bar */}
              <div className="vc-ai-search">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
                <input value={aiSearch} onChange={e => setAiSearch(e.target.value)} placeholder="搜索对话分析..." />
                {aiSearch && <button className="vc-ai-search-clear" onClick={() => setAiSearch("")}>{ICN.x}</button>}
              </div>
              <div className="vc-ai-panel-body">
                {aiThinking && (
                  <div className="vc-ai-thinking-bar"><span className="vc-ai-thinking-pulse" />小文正在分析...</div>
                )}
                {filteredEntries.length === 0 && !aiThinking && (
                  <div className="vc-ai-empty">
                    <div className="vc-ai-empty-icon">{ICN.spark}</div>
                    {kw ? <p>未找到包含「{kw}」的分析记录</p> : (
                      <>
                        <p>在聊天中 @小文 即可获得 AI 回复</p>
                        <p style={{ fontSize: 12 }}>回复会在此显示完整 Markdown 内容</p>
                      </>
                    )}
                  </div>
                )}
                {[...filteredEntries].reverse().map((entry, i) => (
                  <div key={entry.id} className="vc-ai-card">
                    <div className="vc-ai-card-head">
                      <span className="vc-ai-card-sender">{entry.sender || "用户"}</span>
                      <span className="vc-ai-card-query">{entry.query.replace("@小文", "").trim().slice(0, 80) || "对话提及"}</span>
                      <span className="vc-ai-card-meta">
                        {entry.mode === "deep" && <span className="vc-ai-mode-badge deep">深度</span>}
                        {entry.mode === "shallow" && <span className="vc-ai-mode-badge">快捷</span>}
                        <span className="vc-ai-card-date">{fmtDate(entry.time)}</span>
                        <span>{fmtTime(entry.time)}</span>
                      </span>
                      <button className="vc-ai-card-del" onClick={() => deleteAiEntry(entry.id)} title="删除此分析">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13"><path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                      </button>
                    </div>
                    <div className="vc-ai-card-body">
                      {i === 0 ? (
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{entry.reply}</ReactMarkdown>
                      ) : (
                        <details>
                          <summary>展开回复（{entry.reply.length} 字）</summary>
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{entry.reply}</ReactMarkdown>
                        </details>
                      )}
                    </div>
                  </div>
                ))}
              </div>
              <div className="vc-ai-panel-input">
                <input value={aiFollowUp} onChange={e => setAiFollowUp(e.target.value)}
                  placeholder="追问小文..." onKeyDown={e => { if (e.key === "Enter") sendAIFollowUp(); }} />
                <button onClick={sendAIFollowUp} disabled={!aiFollowUp.trim()}>{ICN.send}</button>
              </div>
              </>
            ) : (
              <>
              <div className="vc-ai-search">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="14" height="14"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>
                <input value={fileSearch} onChange={e => setFileSearch(e.target.value)} placeholder="搜索文件名或发送者..." />
                {fileSearch && <button className="vc-ai-search-clear" onClick={() => setFileSearch("")}>{ICN.x}</button>}
              </div>
              <div className="vc-ai-panel-body">
                <div className="vc-ai-file-header">
                  <span>房间文件 ({filteredFiles.length})</span>
                  <button className="vc-ai-file-upload-btn" onClick={() => fileInputRef.current?.click()}>{ICN.file} 上传</button>
                </div>
                {filteredFiles.length === 0 ? (
                  <div className="vc-ai-empty">
                    <div className="vc-ai-empty-icon">{ICN.file}</div>
                    {fkw ? <p>未找到包含「{fkw}」的文件</p> : (
                      <>
                        <p>暂无文件</p>
                        <p style={{ fontSize: 12 }}>在聊天中发送文件，或点击上传</p>
                      </>
                    )}
                  </div>
                ) : (
                  <div className="vc-ai-file-list">
                    {filteredFiles.map(f => (
                      <a key={f.msg_id} href={`${API}${f.file_meta?.url}`} target="_blank" rel="noreferrer" className="vc-ai-file-item">
                        <span className="vc-ai-file-icon">{(f.file_meta?.content_type || "").startsWith("image/") ? "🖼" : "📄"}</span>
                        <div className="vc-ai-file-info">
                          <div className="vc-ai-file-name">{f.file_meta?.filename}</div>
                          <div className="vc-ai-file-meta">
                            <span>{f.sender_name}</span> · <span>{((f.file_meta?.size || 0) / 1024).toFixed(1)} KB</span> · <span>{fmtDate(f.created_at)} {fmtTime(f.created_at)}</span>
                          </div>
                        </div>
                      </a>
                    ))}
                  </div>
                )}
              </div>
              </>
            )}
          </div>
          </>
          );
        })()}

        {/* ══════ INFO PANEL ══════ */}
        {showInfo && activeRoom && !showAI && (
          <div className="vc-info-panel">
            <div className="vc-info-header">
              <h4>{currentRoom?.name}</h4>
              <button className="vc-icon-btn" onClick={() => setShowInfo(false)}>{ICN.x}</button>
            </div>
            <div className="vc-info-tabs">
              <button className={`vc-info-tab${infoTab === "members" ? " active" : ""}`} onClick={() => setInfoTab("members")}>成员 ({currentMembers.length})</button>
              <button className={`vc-info-tab${infoTab === "files" ? " active" : ""}`} onClick={() => { setInfoTab("files"); loadFiles(); }}>文件</button>
            </div>
            <div className="vc-info-body">
              {infoTab === "members" && (
                <>
                  {currentMembers.map(m => {
                    const c = contacts.find(cc => cc.user_id === m);
                    const dname = c?.display_name || m;
                    return (
                      <div key={m} className="vc-info-member">
                        <Avatar id={m} name={dname} size={32} />
                        <div className="vc-info-member-detail">
                          <span className="vc-info-member-name">{dname}</span>
                          {currentRoom?.admin_ids?.includes(m) && <span className="vc-admin-tag">管理员</span>}
                        </div>
                      </div>
                    );
                  })}
                  <details className="vc-invite-section">
                    <summary>邀请新成员</summary>
                    {contacts.filter(c => c.role !== "ai" && !currentMembers.includes(c.user_id)).map(c => (
                      <div key={c.user_id} className="vc-info-member vc-clickable" onClick={async () => {
                        await fetch(`${API}/api/chat/rooms/${activeRoom}/members`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ user_id: c.user_id }) });
                        loadRooms(); const r = await fetch(`${API}/api/chat/rooms/${activeRoom}`); const d = await r.json(); if (d.room) setRooms(prev => prev.map(rm => rm.room_id === activeRoom ? d.room : rm));
                      }}>
                        <Avatar id={c.user_id} name={c.display_name} size={32} />
                        <span className="vc-info-member-name">{c.display_name}</span>
                        <span className="vc-invite-plus">+</span>
                      </div>
                    ))}
                  </details>
                  <button className="vc-danger-btn" onClick={() => deleteRoom(activeRoom)}>删除聊天室</button>
                </>
              )}
              {infoTab === "files" && (
                <>
                  {roomFiles.length === 0 && <div className="vc-empty-hint">暂无文件</div>}
                  {roomFiles.map(f => (
                    <a key={f.msg_id} href={`${API}${f.file_meta?.url}`} target="_blank" rel="noreferrer" className="vc-info-file">
                      <span className="vc-info-file-icon">{f.type === "image" ? "🖼" : ""}{f.type !== "image" && ICN.file}</span>
                      <div><div className="vc-info-file-name">{f.file_meta?.filename}</div><div className="vc-info-file-meta">{f.sender_name} · {((f.file_meta?.size || 0) / 1024).toFixed(1)}KB</div></div>
                    </a>
                  ))}
                </>
              )}
            </div>
          </div>
        )}
      </main>

      {/* ══════ FLOATING VIDEO (P4) ══════ */}
      {videoActive && videoFloat && (
        <div className="vc-video-float" style={{ right: 20 - videoPos.x, bottom: 20 - videoPos.y }}
          onMouseDown={e => { videoDragRef.current = { startX: e.clientX, startY: e.clientY, x: videoPos.x, y: videoPos.y }; const move = (ev: MouseEvent) => { setVideoPos({ x: videoDragRef.current.x - (ev.clientX - videoDragRef.current.startX), y: videoDragRef.current.y - (ev.clientY - videoDragRef.current.startY) }); }; const up = () => { document.removeEventListener("mousemove", move); document.removeEventListener("mouseup", up); }; document.addEventListener("mousemove", move); document.addEventListener("mouseup", up); }}>
          <video ref={remoteVideoRef} autoPlay playsInline className="vc-video-main" />
          <video ref={localVideoRef} autoPlay playsInline muted className="vc-video-pip" />
          <div className="vc-video-controls">
            <span className="vc-video-timer">{fmtDuration(callTimer)}</span>
            <button className={`vc-vc-btn${muted ? " active" : ""}`} onClick={toggleMute}>{muted ? ICN.micOff : ICN.mic}</button>
            <button className="vc-vc-btn danger" onClick={endCall}>{ICN.phone}</button>
            <button className="vc-vc-btn" onClick={() => setVideoFloat(false)} title="返回">{ICN.back}</button>
          </div>
        </div>
      )}

      {/* ══════ CONTEXT MENU (P1) ══════ */}
      {ctxMenu && (
        <div className="vc-context-menu" style={{ left: ctxMenu.x, top: ctxMenu.y }}>
          <div className="vc-context-item" onClick={() => { copyMsg(ctxMenu.msg.content); }}>{ICN.copy} 复制</div>
          <div className="vc-context-item" onClick={() => { setReplyTo(ctxMenu.msg); setCtxMenu(null); }}>{ICN.reply} 回复</div>
          <div className="vc-context-item" onClick={() => { setForwardTarget("pick"); setSelectedMsgs(new Set([ctxMenu.msg.msg_id])); setCtxMenu(null); }}>{ICN.forward} 转发</div>
          <div className="vc-context-sep" />
          <div className="vc-context-item" onClick={() => { setMultiSelect(true); setSelectedMsgs(new Set([ctxMenu.msg.msg_id])); setCtxMenu(null); }}>{ICN.check} 多选</div>
          {ctxMenu.msg.sender_id === uid && (
            <div className="vc-context-item danger" onClick={() => { setCtxMenu(null); }}>{ICN.trash} 删除</div>
          )}
        </div>
      )}

      {/* ══════ FORWARD ROOM PICKER (P1) ══════ */}
      {forwardTarget === "pick" && (
        <div className="vc-overlay" onClick={() => setForwardTarget(null)}>
          <div className="vc-forward-modal" onClick={e => e.stopPropagation()}>
            <h3>转发到</h3>
            <div className="vc-forward-list">
              {rooms.filter(r => r.room_id !== activeRoom).map(r => (
                <div key={r.room_id} className="vc-forward-room" onClick={() => { setForwardTarget(r.room_id); }}>
                  {r.type === "direct" ? <Avatar id={r.members.find(m => m !== uid) || ""} name={r.name} size={32} /> : <div className="vc-room-avatar-group small">{ICN.users}</div>}
                  <span>{r.name}</span>
                </div>
              ))}
            </div>
            <div className="vc-modal-footer">
              <button className="vc-modal-cancel" onClick={() => { setForwardTarget(null); if (!multiSelect) setSelectedMsgs(new Set()); }}>取消</button>
            </div>
          </div>
        </div>
      )}
      {forwardTarget && forwardTarget !== "pick" && (
        <div className="vc-overlay" onClick={() => setForwardTarget(null)}>
          <div className="vc-forward-modal" onClick={e => e.stopPropagation()}>
            <h3>确认转发 {selectedMsgs.size} 条消息？</h3>
            <div className="vc-modal-footer">
              <button className="vc-modal-cancel" onClick={() => setForwardTarget(null)}>取消</button>
              <button className="vc-modal-ok" onClick={forwardSelected}>确认转发</button>
            </div>
          </div>
        </div>
      )}

      {/* ══════ CREATE ROOM MODAL ══════ */}
      {showCreate && (
        <div className="vc-overlay" onClick={() => setShowCreate(false)}>
          <div className="vc-modal" onClick={e => e.stopPropagation()}>
            <h3>发起群聊</h3>
            <input className="vc-modal-input" placeholder="群聊名称" value={newRoomName} onChange={e => setNewRoomName(e.target.value)} autoFocus />
            <div className="vc-modal-member-label">选择成员</div>
            <div className="vc-modal-member-list">
              {contacts.filter(c => c.role !== "ai").map(c => {
                const checked = newRoomMembers.includes(c.user_id);
                return (
                  <label key={c.user_id} className={`vc-modal-member${checked ? " selected" : ""}`}>
                    <input type="checkbox" checked={checked} onChange={() => setNewRoomMembers(prev => checked ? prev.filter(x => x !== c.user_id) : [...prev, c.user_id])} />
                    <Avatar id={c.user_id} name={c.display_name} size={30} />
                    <span>{c.display_name}</span>
                    <span className="vc-modal-member-tag">{c.role === "teacher" ? "老师" : c.team_name || "队友"}</span>
                  </label>
                );
              })}
            </div>
            <div className="vc-modal-footer">
              <button className="vc-modal-cancel" onClick={() => setShowCreate(false)}>取消</button>
              <button className="vc-modal-ok" onClick={() => createRoom(newRoomName || `群聊(${newRoomMembers.length + 1}人)`, newRoomMembers)} disabled={newRoomMembers.length === 0}>创建 ({newRoomMembers.length} 人)</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
