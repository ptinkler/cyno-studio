<!-- The strip of attachments above the prompt: an add tile, each attachment (dimmed when the model
 can't use it, clickable to mention it in the prompt), and the "remove unused" / "clear all" notes. -->
<script setup>
defineProps({
  attachments: { type: Array, default: () => [] },
  unused: { type: Object, default: () => new Set() }, // keys of attachments the selected model can't use
  insertable: { type: Object, default: () => ({}) }, // attachment key -> the ref it can be mentioned as
  mediaMode: { type: Boolean, default: false }, // image / video mode: references can be added
  audioClip: { type: Boolean, default: false }, // audio mode with a voice-clone model: one reference clip
})
defineEmits(['add-clip', 'library', 'insert', 'remove', 'clear', 'remove-unused'])

const canInsert = (a, insertable) => !a.uploading && !!insertable[a.key]
</script>

<template>
  <div v-if="attachments.length || mediaMode || audioClip" class="atts">
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
      v-for="a in attachments"
      :key="a.key"
      class="att"
      :class="{ uploading: a.uploading, ins: canInsert(a, insertable), unused: unused.has(a.key) }"
      :title="
        unused.has(a.key)
          ? 'This model can\'t use this — it won\'t be sent'
          : canInsert(a, insertable)
            ? 'Click to add this reference to the prompt'
            : ''
      "
      @click="$emit('insert', a)"
    >
      <div class="att-media">
        <div v-if="a.audio" class="att-audio" title="Audio reference">🔊</div>
        <video
          v-else-if="a.video"
          :src="a.preview"
          muted
          playsinline
          disablepictureinpicture
          preload="metadata"
        ></video>
        <img v-else :src="a.preview" alt="attachment" />
      </div>
      <button class="attx" title="Remove" @click.stop="$emit('remove', a)">×</button>
      <!-- Hover: a slightly larger still preview (no playback / PiP) -->
      <div class="att-zoom">
        <video v-if="a.video" :src="a.preview" muted playsinline disablepictureinpicture preload="metadata"></video>
        <span v-else-if="a.audio" class="zoom-audio">🔊</span>
        <img v-else :src="a.preview" alt="" />
      </div>
    </div>
  </div>
  <div v-if="unused.size" class="unused-note">
    {{ unused.size }} attachment{{ unused.size === 1 ? '' : 's' }} won't be sent — this model can't use
    {{ unused.size === 1 ? 'it' : 'them' }}.
    <button class="clearall" @click="$emit('remove-unused')">Remove</button>
  </div>
  <div v-if="attachments.length" class="clearrow">
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
