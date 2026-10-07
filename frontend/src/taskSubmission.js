// Tab-local state only: never persist credentials, files or task text in browser storage.
export function createTaskSubmission(makeKey = () => crypto.randomUUID()) {
  let attempt = null;
  let active = false;

  return {
    get active() { return active; },
    reset() {
      if (active) return false;
      attempt = null;
      return true;
    },
    async submit({ owner, payload, file, upload, send }) {
      // Synchronous guard also catches clicks before React has rendered disabled controls.
      if (active) return null;
      active = true;
      try {
        const signature = JSON.stringify(payload);
        if (!attempt || attempt.owner !== owner) {
          attempt = { owner, signature, file, key: makeKey(), payload: null };
        } else if (attempt.signature !== signature || attempt.file !== file) {
          throw new Error("Для изменения отправленного запроса нажмите «Новая задача».");
        }
        if (!attempt.payload) {
          const artifact = file ? await upload(file) : null;
          attempt.payload = { ...payload, attachment_ids: artifact ? [artifact.id] : [] };
        }
        // Retain the key AND uploaded artifact after any error, including invalid JSON.
        return await send(attempt.payload, attempt.key);
      } finally {
        active = false;
      }
    },
  };
}
