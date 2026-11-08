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

/** Resolve admitted image bytes in place, never replace visual evidence with a caption.
 * Only visual compression calls this; controlled native baselines retain original refs.
 */
export async function inlineImagesForRenderer(messages, attachments, signal, occurrenceOffset = 0) {
  const cache = new Map();
  const result = [];
  for (const [messageIndex, message] of messages.entries()) {
    const content = [];
    for (const [blockIndex, block] of message.content.entries()) {
      if (block.type !== 'image') { content.push(block); continue; }
      if (block.offloaded) throw new Error('Visual evidence has been offloaded; cannot render original pixels');
      const ref = block.attachment;
      if (!ref?.attachmentId) throw new Error('Visual evidence has no durable attachment identity');
      let stored = cache.get(ref.attachmentId);
      if (!stored) {
        stored = await attachments.readImage(ref, signal);
        if (!stored?.data?.length) throw new Error('Visual evidence bytes are missing');
        cache.set(ref.attachmentId, stored);
      }
      const mediaType = stored.ref?.mediaType ?? ref.mediaType;
      if (!['image/png', 'image/jpeg', 'image/webp', 'image/gif'].includes(mediaType)) {
        throw new Error(`Unsupported visual evidence media type: ${mediaType}`);
      }
      content.push({
        type: 'image_url',
        image_url: { url: `data:${mediaType};base64,${Buffer.from(stored.data).toString('base64')}`, ...(block.aclImageDetail?{detail:block.aclImageDetail}:{}) },
        source_attachment_id: ref.attachmentId,
        source_occurrence: `${message.id ?? `message-${occurrenceOffset + messageIndex}`}:block-${blockIndex}`,
      });
    }
    result.push({ ...message, content });
  }
  return result;
}
