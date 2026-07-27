export const aiUrl = {
  chat: {
    stream: "v1/chat/completions",
    stop: "/api/v1/chat/stop",
  },
  session: {
    base: "/api/v1/session",
    list: "/api/v1/session/list",
    messages: "/api/v1/session/messages",
    detail: "/api/v1/session/detail",
    delete: "/api/v1/session/delete",
    all: "/api/v1/session/all",
    create: "/api/v1/session/create",
    stats: "/api/v1/session/stats",
  },
};
