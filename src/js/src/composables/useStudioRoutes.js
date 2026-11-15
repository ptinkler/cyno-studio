import { ref, computed, watch, nextTick } from 'vue'

// Where the Studio is: its centre pane (a thread, the settings, media…) is a real route so the back button works.
// Holds the route-derived view state, the navigation helpers the panes call, and the sync from route to state.
export function useStudioRoutes({ router, route, studio, threadView }) {
  const {
    threads,
    spaces,
    active,
    activeKind,
    newThread,
    openThread,
    loadStatus,
    loadFavourites,
    setThreadKind,
    removeSpace,
  } = studio
  const navFilter = ref('all') // list filter: 'all' | 'chat' | 'gallery' (Favourites is its own route)
  const centerView = ref('thread') // 'thread' | 'space' | 'media' | 'settings' | 'favourites' — derived from the route
  // The sidebar shows Favourites as active when its route is open.
  const sidebarFilter = computed(() => (centerView.value === 'favourites' ? 'favourites' : navFilter.value))
  function onFilter(f) {
    if (f === 'favourites') router.push('/favourites')
    else {
      navFilter.value = f
      if (centerView.value === 'favourites') goThread()
    }
  }
  const activeSpace = ref(null)
  const spaceThreads = computed(() => threads.value.filter(t => t.space_id === activeSpace.value?.id))

  function ensureSpace(spaceId) {
    const found = spaces.value.find(s => s.id === Number(spaceId))
    if (found) activeSpace.value = found
  }
  // The space may not be loaded yet on a cold deep-link; bind it once lists load.
  watch(spaces, () => {
    if (route.name === 'studio-space') ensureSpace(route.params.spaceId)
  })

  function openSpace(space) {
    router.push(`/space/${space.id}`)
  }
  async function deleteSpaceView(space) {
    await removeSpace(space)
    if (activeSpace.value?.id === space.id) goThread()
  }

  let pendingKind = 'chat' // the kind a brand-new thread (/) opens on
  function goThread() {
    router.push(active.value ? `/${active.value}` : '/')
  }
  function goSettings() {
    router.push('/settings')
  }
  function goTools() {
    router.push('/tools')
  }
  function goMedia() {
    router.push('/media')
  }
  function openThreadView(id) {
    router.push(`/${id}`)
  }
  const composerRef = ref(null)
  async function newThreadView(kind = 'chat') {
    pendingKind = kind
    // ?new=gallery so the link opens as a gallery in a new tab too
    const to = kind === 'gallery' ? '/?new=gallery' : '/'
    if (route.name === 'studio')
      newThread(kind) // already on the home route: just reset
    else await router.push(to)
    await nextTick()
    composerRef.value?.focusPrompt()
  }
  // One toggle does both jobs: it switches the view *and* makes that the view the
  // thread opens on next time (there is no separate "default view" switch).
  function setThreadView(v) {
    if (activeKind.value !== v) setThreadKind(v)
    if (active.value) router.push(`/${active.value}/${v}`)
    else threadView.value = v // unsaved new thread has no id to route
  }
  function goInstructions() {
    router.push('/instructions')
  }
  // Settings "Tools" links → in-Studio panes.
  const STUDIO_PANE_PATH = {
    usage: '/usage',
    characters: '/characters',
    instructions: '/instructions',
    'request-log': '/requests',
    presets: '/presets',
  }
  function onSettingsNavigate(dest) {
    const path = STUDIO_PANE_PATH[dest]
    if (path) router.push(path)
    else router.push({ name: dest })
  }

  // Which center pane each route name shows (threads handled separately below).
  const PANE_FOR_ROUTE = {
    'studio-settings': 'settings',
    'studio-tools': 'tools',
    'studio-media': 'media',
    'studio-usage': 'usage',
    'studio-characters': 'characters',
    'studio-presets': 'presets',
    'studio-instructions': 'instructions',
    'studio-requests': 'requests',
    'studio-favourites': 'favourites',
    'studio-space': 'space',
  }
  function openPane(pane) {
    centerView.value = pane
    if (pane === 'usage')
      loadStatus() // refresh balances when opening usage
    else if (pane === 'favourites') loadFavourites()
    else if (pane === 'space') ensureSpace(route.params.spaceId)
  }
  // studio-thread (/:id[/:view]) or studio (/ = new thread)
  async function openThreadRoute() {
    centerView.value = 'thread'
    const id = route.params.id || null
    if (!id) {
      // ?new=gallery lets "New gallery" work as a link (opened in a new tab,
      // bookmarked), not just as a click that set pendingKind on the way here
      newThread(route.query.new === 'gallery' ? 'gallery' : pendingKind)
      pendingKind = 'chat'
      return
    }
    // A thread that fails to load (stale URL) falls back to home.
    if (id !== active.value && !(await openThread(id))) {
      router.replace('/')
      return
    }
    if (route.params.view === 'chat' || route.params.view === 'gallery') threadView.value = route.params.view
  }
  // Drive the center pane + active thread from the current route.
  async function syncFromRoute() {
    const pane = PANE_FOR_ROUTE[route.name]
    if (pane) openPane(pane)
    else await openThreadRoute()
  }
  watch(() => route.fullPath, syncFromRoute)

  // When a thread appears/changes outside navigation (first send on a new thread,
  // or a fork), reflect its id in the URL so the address bar and back button stay
  // correct. replace (not push) so back doesn't land on the empty /studio.
  watch(active, id => {
    if (id && centerView.value === 'thread' && route.params.id !== id) router.replace(`/${id}`)
  })

  return {
    centerView,
    sidebarFilter,
    onFilter,
    activeSpace,
    spaceThreads,
    composerRef,
    openSpace,
    deleteSpaceView,
    goThread,
    goSettings,
    goTools,
    goMedia,
    goInstructions,
    openThreadView,
    newThreadView,
    setThreadView,
    onSettingsNavigate,
    syncFromRoute,
  }
}
