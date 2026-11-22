export type MessageData = Readonly<Record<string, unknown>>;

const NAMED_PLACEHOLDER = /{{\s*([A-Za-z][A-Za-z0-9_]*)\s*}}/g;

export const formatMessage = (message: string, data: MessageData): string =>
  message.replace(NAMED_PLACEHOLDER, (placeholder, key: string) =>
    Object.prototype.hasOwnProperty.call(data, key) ? String(data[key]) : placeholder
  );
