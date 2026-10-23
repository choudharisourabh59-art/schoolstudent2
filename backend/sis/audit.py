import contextvars
_ctx = contextvars.ContextVar("audit_ctx", default=(None, None))

def set_current(user, ip):
    _ctx.set((user, ip))

def get_current():
    return _ctx.get()
