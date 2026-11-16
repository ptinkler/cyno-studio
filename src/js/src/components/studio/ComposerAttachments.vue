<script setup lang="ts">
import type { Attachment } from '../../composables/useChatAttachments'
import type { RefItem } from '../../utils/refItems'

const props = withDefaults(
  defineProps<{
    attachments?: readonly Attachment[] | undefined
    /** Keys of attachments the selected model can't use. */
    unused?: ReadonlySet<string> | undefined
    /** Attachment key -> the ref it can be mentioned as. */
    insertable?: Readonly<Record<string, RefItem>> | undefined
    /** Image / video mode: references can be added. */
    mediaMode?: boolean | undefined
    /** Audio mode with a voice-clone model: one reference clip. */
    audioClip?: boolean | undefined
  }>(),
  {
    attachments: () => [],
    unused: () => new Set<string>(),
    insertable: () => ({}),
    mediaMode: false,
    audioClip: false,
  },
)
defineEmits<{
  'add-clip': []
  library: []
  insert: [attachment: Attachment]
  remove: [attachment: Attachment]
  clear: []
  'remove-unused': []
}>()

const canInsert = (attachment: Attachment, insertable: Readonly<Record<string, RefItem>>): boolean =>
  !attachment.uploading && !!insertable[attachment.key]
</script>

<template>
  <div v-if="props.attachments.length || mediaMode || audioClip" class="atts">
    <div v-if="mediaMode || audioClip" class="plus">
      <button
        class="addtile"
        :title="audioClip ? 'Upload an audio clip' : 'Add references — pick from your media or upload'"
        @click="audioClip ? $emit('add-clip') : $emit('library')"
      >
        +
      </button>
    </div>
    <div
      v-for="a in props.attachments"
      :key="a.key"
      class="att"
      :class="{ uploading: a.uploading, ins: canInsert(a, props.insertable), unused: props.unused.has(a.key) }"
      :title="
        props.unused.has(a.key)
          ? 'This model can\'t use this — it won\'t be sent'
          : canInsert(a, props.insertable)
            ? 'Click to add this reference to the prompt'
            : ''
      "
      @click="$emit('insert', a)"
    >
      <div class="att-media">
        <div v-if="a.audio" class="att-audio" title="Audio reference">🔊</div>
        <video
          v-else-if="a.video"
          :src="a.preview ?? undefined"
          muted
          playsinline
          disablepictureinpicture
          preload="metadata"
        ></video>
        <img v-else :src="a.preview ?? undefined" alt="attachment" />
      </div>
      <button class="attx" title="Remove" @click.stop="$emit('remove', a)">×</button>
      <!-- Hover: a slightly larger still preview (no playback / PiP) -->
      <div class="att-zoom">
        <video
          v-if="a.video"
          :src="a.preview ?? undefined"
          muted
          playsinline
          disablepictureinpicture
          preload="metadata"
        ></video>
        <span v-else-if="a.audio" class="zoom-audio">🔊</span>
        <img v-else :src="a.preview ?? undefined" alt="" />
      </div>
    </div>
  </div>
  <div v-if="props.unused.size" class="unused-note">
    {{ props.unused.size }} attachment{{ props.unused.size === 1 ? '' : 's' }} won't be sent — this model can't use
    {{ props.unused.size === 1 ? 'it' : 'them' }}.
    <button class="clearall" @click="$emit('remove-unused')">Remove</button>
  </div>
  <div v-if="props.attachments.length" class="clearrow">
    <button class="clearall" title="Remove every attached image and video" @click="$emit('clear')">Clear all</button>
  </div>
</template>

<style scoped>
.clearrow {
  position: absolute;
  top: 10px;
  right: 12px;
  z-index: 2;
}
.clearall {
  border: 1px solid var(--sborder);
  border-radius: 999px;
  background: var(--sbg);
  color: var(--smuted);
  font: inherit;
  font-size: 11px;
  padding: 2px 9px;
  cursor: pointer;
}
.clearall:hover {
  color: var(--sdanger);
  border-color: var(--sdanger);
}
.atts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-bottom: 8px;
}
.att {
  position: relative;
  width: 52px;
  height: 52px;
}
.att.unused {
  opacity: 0.4;
  filter: grayscale(1);
}
.unused-note {
  padding: 2px 12px 6px;
  font-size: 12px;
  color: var(--swarn);
}
.att.ins {
  cursor: pointer;
}
.att-media {
  width: 100%;
  height: 100%;
  border-radius: 9px;
  overflow: hidden;
  border: 1px solid var(--sborder);
}
.att.ins:hover .att-media {
  border-color: var(--saccent);
}
.att-media video,
.att-media img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.att-audio {
  width: 100%;
  height: 100%;
  display: grid;
  place-items: center;
  font-size: 22px;
  background: var(--saccent-soft);
}
.att:hover .att-zoom {
  display: block;
}
.att-zoom img,
.att-zoom video {
  display: block;
  max-width: 200px;
  max-height: 200px;
  border-radius: 5px;
}
.zoom-audio {
  display: grid;
  place-items: center;
  width: 120px;
  height: 64px;
  font-size: 30px;
}
.plus {
  position: relative;
}
.addtile {
  width: 52px;
  height: 52px;
  border-radius: 9px;
  border: 1px dashed var(--sborder);
  background: var(--sbg2);
  color: var(--smuted);
  font-size: 22px;
  cursor: pointer;
}
.addtile:hover {
  border-color: var(--saccent);
  color: var(--sfg);
}
.att.uploading {
  opacity: 0.5;
}
.attx {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 17px;
  height: 17px;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 5px;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
}
/* Hover: a larger still preview floating above the thumbnail */
.att-zoom {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  display: none;
  z-index: 30;
  padding: 3px;
  background: var(--spanel2);
  border: 1px solid var(--sborder);
  border-radius: var(--r);
  box-shadow: var(--shadow-pop);
}
</style>
