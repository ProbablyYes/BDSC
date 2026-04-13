"use client";

import { Suspense, useEffect, useRef, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";

const API = (process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8037").trim().replace(/\/+$/, "");
const WS_BASE = API.replace(/^http/, "ws");

type Msg = {
  msg_id: string; room_id: string; sender_id: string; sender_name: string;
  type: string; content: string; mentions: string[]; reply_to?: string;
  file_meta?: { filename: string; url: string; size: number; content_type: string };
  reactions: Record<string, string[]>; created_at: string;
};

function fmtTime(iso: string) {
  try { return new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }); } catch { return ""; }
}
function avatarColor(id: string) {
  const colors = ["#6B8AFF","#51cf66","#fcc419","#ff6b6b","#845ef7","#22b8cf","#ff922b","#e64980"];
  let h = 0; for (let i = 0; i < id.length; i++) h = id.charCodeAt(i) + ((h << 5) - h);
  return colors[Math.abs(h) % colors.length];
}

function PopChatContent() {
  const params = useSearchParams();
  const roomId = params.get("room") || "";
  const userId = params.get("user_id") || "";
  const userName = params.get("user_name") || "";

  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [roomName, setRoomName] = useState("聊天");
  const wsRef = useRef<WebSocket | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const loadMessages = useCallback(async () => {
    if (!roomId) return;
    try {
      const r = await fetch(`${API}/api/chat/rooms/${roomId}/messages?limit=100`);
      const d = await r.json(); setMessages(d.messages || []);
    } catch {}
    try {
      const r2 = await fetch(`${API}/api/chat/rooms/${roomId}`);
      const d2 = await r2.json(); if (d2.room?.name) setRoomName(d2.room.name);
    } catch {}
  }, [roomId]);

  useEffect(() => {
    if (!roomId || !userId) return;
    loadMessages();
    const ws = new WebSocket(`${WS_BASE}/ws/chat/${roomId}?user_id=${userId}&user_name=${encodeURIComponent(userName)}`);
    wsRef.current = ws;
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === "new_message") {
          setMessages(prev => prev.some(m => m.msg_id === data.message.msg_id) ? prev : [...prev, data.message]);
        }
      } catch {}
    };
    return () => { ws.close(); };
  }, [roomId, userId, userName, loadMessages]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  const send = () => {
    const text = input.trim(); if (!text) return;
    const mentions: string[] = [];
    if (text.includes("@小文")) mentions.push("ai_xiaowen");
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "text", content: text, mentions }));
    }
    setInput("");
  };

  if (!roomId) return <div style={{ padding: 24, color: "#888" }}>缺少房间参数</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "var(--bg-primary, #f5f6fa)", fontFamily: "inherit" }}>
      <header style={{ padding: "10px 16px", borderBottom: "1px solid var(--border, #e0e0e0)", background: "var(--bg-secondary, #fff)", fontWeight: 700, fontSize: 15 }}>
        {roomName}
        <span style={{ fontSize: 11, color: "#999", marginLeft: 8 }}>弹出窗口</span>
      </header>
      <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
        {messages.map(m => {
          const isOwn = m.sender_id === userId;
          const isSystem = m.type === "system";
          if (isSystem) return <div key={m.msg_id} style={{ textAlign: "center", fontSize: 11, color: "#999", margin: "6px 0" }}>{m.content}</div>;
          return (
            <div key={m.msg_id} style={{ display: "flex", gap: 8, marginBottom: 10, flexDirection: isOwn ? "row-reverse" : "row", maxWidth: "80%" , marginLeft: isOwn ? "auto" : 0 }}>
              {!isOwn && (
                <div style={{ width: 32, height: 32, borderRadius: "50%", background: m.sender_id === "ai_xiaowen" ? "#51cf66" : avatarColor(m.sender_id), display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontSize: 12, fontWeight: 700, flexShrink: 0 }}>
                  {m.sender_id === "ai_xiaowen" ? "文" : (m.sender_name?.[0] || "?").toUpperCase()}
                </div>
              )}
              <div>
                {!isOwn && <div style={{ fontSize: 11, color: "#999", marginBottom: 2 }}>{m.sender_name}</div>}
                <div style={{ padding: "8px 12px", borderRadius: isOwn ? "14px 4px 14px 14px" : "4px 14px 14px 14px", background: isOwn ? "#2b5fea" : "#fff", color: isOwn ? "#fff" : "#222", fontSize: 14, lineHeight: 1.6, wordBreak: "break-word", whiteSpace: "pre-wrap", border: isOwn ? "none" : "1px solid #e8e8e8" }}>
                  {m.content}
                </div>
                <div style={{ fontSize: 10, color: "#999", marginTop: 2, textAlign: isOwn ? "right" : "left" }}>{fmtTime(m.created_at)}</div>
              </div>
            </div>
          );
        })}
        <div ref={endRef} />
      </div>
      <div style={{ display: "flex", gap: 8, padding: "10px 16px", borderTop: "1px solid var(--border, #e0e0e0)", background: "var(--bg-secondary, #fff)" }}>
        <input value={input} onChange={e => setInput(e.target.value)} onKeyDown={e => { if (e.key === "Enter") send(); }}
          placeholder="输入消息..." style={{ flex: 1, padding: "8px 12px", border: "1px solid #ddd", borderRadius: 10, fontSize: 14, outline: "none" }} />
        <button onClick={send} disabled={!input.trim()}
          style={{ padding: "8px 18px", borderRadius: 10, border: "none", background: "#2b5fea", color: "#fff", fontWeight: 600, cursor: "pointer", opacity: input.trim() ? 1 : 0.4 }}>
          发送
        </button>
      </div>
    </div>
  );
}

export default function PopChatPage() {
  return (
    <Suspense fallback={<div style={{ padding: 24, color: "#888" }}>正在加载聊天窗口...</div>}>
      <PopChatContent />
    </Suspense>
  );
}
