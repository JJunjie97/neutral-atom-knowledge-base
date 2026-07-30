import {
  CircleAlert,
  KeyRound,
  LoaderCircle,
  LockKeyhole,
  PlugZap,
  Server,
  ShieldCheck,
  Unplug,
} from "lucide-react";

export type ConnectionMode = "detecting" | "local" | "public";
export type ConnectionState = "offline" | "connecting" | "connected" | "error";

type Props = {
  mode: ConnectionMode;
  state: ConnectionState;
  apiUrl: string;
  token: string;
  error: string | null;
  onApiUrlChange: (value: string) => void;
  onTokenChange: (value: string) => void;
  onConnect: () => void;
  onDisconnect: () => void;
};

const START_COMMAND =
  "python -m neutral_atom_graph admin --host 127.0.0.1 --port 8765";

export default function ConnectionPanel({
  mode,
  state,
  apiUrl,
  token,
  error,
  onApiUrlChange,
  onTokenChange,
  onConnect,
  onDisconnect,
}: Props) {
  const isPublic = mode === "public";
  const connected = state === "connected";

  return (
    <section className="admin-card connection-card" aria-labelledby="connection-title">
      <div className="admin-card-heading">
        <div>
          <span className="admin-kicker">LOCAL CONTROL PLANE</span>
          <h2 id="connection-title">数据库连接</h2>
        </div>
        <span
          className={`connection-pill is-${isPublic ? "public" : state}`}
          role="status"
        >
          {state === "connecting" ? (
            <LoaderCircle className="spin" size={14} />
          ) : connected ? (
            <ShieldCheck size={14} />
          ) : isPublic ? (
            <LockKeyhole size={14} />
          ) : (
            <Unplug size={14} />
          )}
          {isPublic
            ? "公开只读"
            : state === "connecting"
              ? "正在验证"
              : connected
                ? "本地可写"
                : "未连接"}
        </span>
      </div>

      {isPublic ? (
        <div className="public-mode-note">
          <LockKeyhole size={19} />
          <div>
            <strong>GitHub Pages 不持有数据库写入权限</strong>
            <p>
              公开站点仅展示静态快照。请在本机启动 Atlas 与管理服务，再从
              <code>localhost</code> 打开此页进行编辑。
            </p>
          </div>
        </div>
      ) : (
        <form
          className="connection-form"
          onSubmit={(event) => {
            event.preventDefault();
            onConnect();
          }}
        >
          <label>
            <span>
              <Server size={14} /> API URL
            </span>
            <input
              autoComplete="off"
              disabled={connected || state === "connecting"}
              inputMode="url"
              onChange={(event) => onApiUrlChange(event.target.value)}
              spellCheck={false}
              type="url"
              value={apiUrl}
            />
          </label>
          <label>
            <span>
              <KeyRound size={14} /> Session token
            </span>
            <input
              autoComplete="off"
              disabled={connected || state === "connecting"}
              onChange={(event) => onTokenChange(event.target.value)}
              placeholder="粘贴服务启动时显示的 token"
              spellCheck={false}
              type="password"
              value={token}
            />
          </label>
          <p className="session-note">
            Token 仅保存在当前标签页的 sessionStorage；关闭标签页后失效。
          </p>
          {error && (
            <div className="admin-inline-error" role="alert">
              <CircleAlert size={15} />
              <span>{error}</span>
            </div>
          )}
          {connected ? (
            <button className="admin-button is-secondary" onClick={onDisconnect} type="button">
              <Unplug size={15} /> 断开连接
            </button>
          ) : (
            <button
              className="admin-button is-primary"
              disabled={state === "connecting" || !token.trim()}
              type="submit"
            >
              {state === "connecting" ? (
                <LoaderCircle className="spin" size={15} />
              ) : (
                <PlugZap size={15} />
              )}
              连接并验证
            </button>
          )}
        </form>
      )}

      <div className="launch-instruction">
        <span>本地启动命令</span>
        <code>{START_COMMAND}</code>
      </div>
    </section>
  );
}
