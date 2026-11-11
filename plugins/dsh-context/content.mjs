import {imageDataURL} from './image-data-url-cache.mjs';
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
      const cacheKey = `${ref.attachmentId}:${ref.mediaType??''}`;
      let url = cache.get(cacheKey);
      if (!url) {
        url = await imageDataURL(attachments, ref, signal);
        cache.set(cacheKey, url);
      }
      content.push({
        type: 'image_url',
        image_url: { url, ...(block.aclImageDetail?{detail:block.aclImageDetail}:{}) },
        source_attachment_id: ref.attachmentId,
        source_occurrence: `${message.id ?? `message-${occurrenceOffset + messageIndex}`}:block-${blockIndex}`,
      });
    }
    result.push({ ...message, content });
  }
  return result;
}
