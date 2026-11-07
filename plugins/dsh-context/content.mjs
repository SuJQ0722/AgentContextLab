/** Separate native image evidence from text without changing attachment references. */
export function separateImages(messages) {
  const images = new Map();
  const text = messages.map(message => ({
    ...message,
    content: message.content.map(block => {
      if (block.type !== 'image') return block;
      const id = block.attachment.attachmentId;
      images.set(id, block);
      return { type: 'text', text: `[Native image ${id}]` };
    }),
  }));
  return { text, images: [...images.values()] };
}

/** Preserve an explicit original task separately from compressed history. */
export function originalTask(messages) {
  const task = messages.find(message => message.role === 'user');
  if (!task) throw new Error('No original user task in compaction region');
  return task.content;
}
