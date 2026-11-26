<script setup lang="ts">
import { computed } from 'vue'
import { vTip } from '../../directives/tip'
import type { Attachment } from '../../composables/useChatAttachments'
import type { RefItem } from '../../utils/refItems'
import type { PlannedRef, RefState } from '../../composables/useRefPlan'

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
    /** Pins, recent images and character images the next message may carry; click to switch one off. */
    planned?: readonly PlannedRef[] | undefined
    /** The References part is folded away. */
    refsHidden?: boolean | undefined
  }>(),
  {
    attachments: () => [],
    unused: () => new Set<string>(),
    insertable: () => ({}),
    mediaMode: false,
    audioClip: false,
    planned: () => [],
    refsHidden: false,
  },
)
defineEmits<{
  'add-clip': []
  library: []
  insert: [attachment: Attachment]
  remove: [attachment: Attachment]
  clear: []
  'remove-unused': []
  'toggle-plan': [ref: string]
  'toggle-refs': []
}>()

const SOURCES = { chat: 'Chat image', character: 'Character image' }
const NOTES: Record<RefState, string> = {
  sent: 'Will be sent. Click to leave it out.',
  off: 'Left out. Click to send it.',
  idle: 'Not sent. Click to send it with the next message.',
  capped: 'Over the Images sent limit, so it is not sent. Click to leave it out for good.',
  dropped: 'The image model takes fewer references, so it is not sent. Click to leave out another instead.',
}

const sentCount = computed(() => props.planned.filter(r => r.state === 'sent').length)

const canInsert = (attachment: Attachment, insertable: Readonly<Record<string, RefItem>>): boolean =>
  !attachment.uploading && !!insertable[attachment.key]
</script>

<template>
  <div v-if="props.attachments.length || props.planned.length || mediaMode || audioClip" class="atts">
    <button
      v-if="mediaMode || audioClip"
      v-tip="audioClip ? 'Upload an audio clip' : 'Add references — pick from your media or upload'"
      class="addtile"
      :aria-label="audioClip ? 'Upload an audio clip' : 'Add references — pick from your media or upload'"
      @click="audioClip ? $emit('add-clip') : $emit('library')"
    >
      <svg class="ic"><use href="#s-plus" /></svg>
    </button>
    <button
      v-if="props.planned.length"
      v-tip="
        `References: ${sentCount} of ${props.planned.length} will be sent. ${props.refsHidden ? 'Click to show them' : 'Click to hide them'}`
      "
      class="refchip"
      :class="{ on: !props.refsHidden }"
      :aria-pressed="!props.refsHidden"
      aria-label="References"
      @click="$emit('toggle-refs')"
    >
      <svg class="ic"><use href="#s-image" /></svg>
      <span class="badge">{{ sentCount }}</span>
    </button>
    <div
      v-for="a in props.attachments"
      :key="a.key"
      v-tip="
        props.unused.has(a.key)
          ? 'This model can\'t use this — it won\'t be sent'
          : canInsert(a, props.insertable)
            ? 'Click to add this reference to the prompt'
            : ''
      "
      class="att"
      :class="{ uploading: a.uploading, ins: canInsert(a, props.insertable), unused: props.unused.has(a.key) }"
      @click="$emit('insert', a)"
    >
      <div class="att-media">
        <div v-if="a.audio" v-tip="'Audio reference'" class="att-audio">🔊</div>
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
      <button v-tip="'Remove'" class="attx" aria-label="Remove" @click.stop="$emit('remove', a)">×</button>
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
    <button
      v-for="r in props.refsHidden ? [] : props.planned"
      :key="r.ref"
      v-tip="`${SOURCES[r.source]}. ${NOTES[r.state]}`"
      class="att plan"
      :class="r.state"
      :aria-pressed="r.state === 'sent'"
      @click="$emit('toggle-plan', r.ref)"
    >
      <div class="att-media"><img :src="r.url" alt="" /></div>
    </button>
  </div>
  <div v-if="props.unused.size" class="unused-note">
    {{ props.unused.size }} attachment{{ props.unused.size === 1 ? '' : 's' }} won't be sent — this model can't use
    {{ props.unused.size === 1 ? 'it' : 'them' }}.
    <button class="clearall" @click="$emit('remove-unused')">Remove</button>
  </div>
  <div v-if="props.attachments.length" class="clearrow">
    <button v-tip="'Clear all'" class="clearicon" aria-label="Clear all" @click="$emit('clear')">
      <svg class="ic sm"><use href="#s-trash" /></svg>
    </button>
  </div>
</template>

<style scoped>
.clearrow {
  position: absolute;
  top: 0.6667rem;
  right: 0.8rem;
  z-index: 2;
}
.clearall {
  border: 1px solid var(--sborder);
  border-radius: 66.6rem;
  background: var(--sbg);
  color: var(--smuted);
  font: inherit;
  font-size: 0.8rem;
  padding: 2px 0.6rem;
  cursor: pointer;
}
.clearall:hover {
  color: var(--sdanger);
  border-color: var(--sdanger);
}
.clearicon {
  display: grid;
  place-items: center;
  width: 1.6rem;
  height: 1.6rem;
  border: none;
  border-radius: 0.4rem;
  background: none;
  color: var(--sfaint);
  cursor: pointer;
}
.clearicon:hover {
  background: var(--shover);
  color: var(--sdanger);
}
.atts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  padding-bottom: 0.4rem;
}
.att {
  position: relative;
  width: 2.6667rem;
  height: 2.6667rem;
}
.att.plan {
  padding: 0;
  border: none;
  background: none;
  cursor: pointer;
}
.att.plan.sent .att-media {
  border: 2px solid var(--saccent);
}
.att.plan.idle,
.att.plan.off,
.att.plan.capped,
.att.plan.dropped {
  opacity: 0.4;
  filter: grayscale(1);
}
.att.unused {
  opacity: 0.4;
  filter: grayscale(1);
}
.unused-note {
  padding: 2px 0.8rem 0.4rem;
  font-size: 0.8rem;
  color: var(--swarn);
}
.att.ins {
  cursor: pointer;
}
.att-media {
  width: 100%;
  height: 100%;
  border-radius: 0.6rem;
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
  font-size: 1.4667rem;
  background: var(--saccent-soft);
}
.att:hover .att-zoom {
  display: block;
}
.att-zoom img,
.att-zoom video {
  display: block;
  max-width: 13.3333rem;
  max-height: 13.3333rem;
  border-radius: 0.3333rem;
}
.zoom-audio {
  display: grid;
  place-items: center;
  width: 8rem;
  height: 4.2667rem;
  font-size: 2rem;
}
/* The + and the References toggle: small icon buttons, the same size, at the start of the row */
.addtile,
.refchip {
  position: relative;
  display: grid;
  place-items: center;
  width: 2.2rem;
  height: 2.2rem;
  padding: 0;
  border-radius: 0.5333rem;
  border: 1px dashed var(--sborder);
  background: none;
  color: var(--smuted);
  cursor: pointer;
}
.refchip {
  border-style: solid;
}
.addtile:hover,
.refchip:hover {
  border-color: var(--saccent);
  color: var(--sfg);
}
.refchip.on {
  border-color: var(--saccent);
  background: var(--saccent-soft);
  color: var(--sfg);
}
.badge {
  position: absolute;
  top: -0.3rem;
  right: -0.3rem;
  min-width: 1rem;
  height: 1rem;
  padding: 0 0.25rem;
  display: grid;
  place-items: center;
  border-radius: 66.6rem;
  background: var(--saccent-fill);
  color: #fff;
  font-size: 0.65rem;
  font-weight: 600;
  line-height: 1;
}
.att.uploading {
  opacity: 0.5;
}
.attx {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 1.1333rem;
  height: 1.1333rem;
  display: grid;
  place-items: center;
  border: none;
  border-radius: 0.3333rem;
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  cursor: pointer;
  font-size: 0.8667rem;
  line-height: 1;
}
/* Hover: a larger still preview floating above the thumbnail */
.att-zoom {
  position: absolute;
  bottom: calc(100% + 0.4rem);
  left: 50%;
  transform: translateX(-50%);
  display: none;
  z-index: var(--z-popover);
  padding: 0.2rem;
  background: var(--spanel2);
  border: 1px solid var(--sborder);
  border-radius: var(--r);
  box-shadow: var(--shadow-pop);
}
</style>
