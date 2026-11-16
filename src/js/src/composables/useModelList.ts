import { computed } from 'vue'
import type { Ref } from 'vue'
import type { Model, ModelKind } from './chatModelsApi'
import { useModelFavourites } from './useModelFavourites'
import { useModelFilters } from './useModelFilters'
import { useShowHidden } from './useShowHidden'
import { useUncensoredOnly } from './useUncensoredOnly'
import { ALL_PROVIDERS, PROVIDER_COLOR, PROVIDER_IDS, TAG_LABELS, providerOf, tagColor, tagLabel } from './modelTags'
import type { Provider } from './modelTags'

const MAX_LISTED = 200 // models shown outside Favourites

/** The model picker's props that decide what it lists. */
export interface ModelListProps {
  models: readonly Model[]
  modelValue: string
  kind: ModelKind
}

/** A provider chip in the filter menu: how many models it has, and its colour. */
export interface ProviderFacet {
  id: Provider
  label: string
  title: string
  n: number
  color: string
}

/** A capability tag in the filter menu. */
export interface TagFacet {
  slug: string
  label: string
  n: number
  color: string
}

export interface ActiveChip {
  key: string
  label: string
  color?: string
  /** Switch this filter off. */
  off: () => void
}

export interface ModelSection {
  id: 'fav' | 'all'
  label: string
  models: Model[]
}

// What the model picker lists: the catalogue narrowed by "Show hidden", "Uncensored only", the provider and tag
// facets and the search text, then split into Favourites and the rest. `props` is the picker's props (reactive);
// `query` is a ref of the search box. The current pick always stays in the list.
export function useModelList(props: ModelListProps, query: Ref<string>) {
  const { favourites, isFavourite, toggleFavourite } = useModelFavourites()
  const { showHidden } = useShowHidden()
  const { uncensoredOnly } = useUncensoredOnly()
  const { filters, toggleProvider, toggleTag, clear: clearFilters, hasActive } = useModelFilters()

  // Hidden models (not enabled for this API key, or retired) only show behind "Show hidden"
  const hiddenCount = computed(() => props.models.filter(m => m.hidden).length)
  const uncensoredCount = computed(
    () => props.models.filter(m => m.uncensored && (showHidden.value || !m.hidden)).length,
  )
  const visibleModels = computed(() =>
    props.models.filter(
      m =>
        m.id === props.modelValue ||
        ((showHidden.value || !m.hidden) && (!uncensoredOnly.value || !uncensoredCount.value || m.uncensored)),
    ),
  )

  // Provider facet: which providers the list spans, with counts. Chips are only
  // offered when more than one provider is present.
  const providerCounts = computed(() => {
    const counts: Partial<Record<Provider, number>> = {}
    for (const m of visibleModels.value) {
      const p = providerOf(m.id)
      counts[p] = (counts[p] ?? 0) + 1
    }
    return counts
  })
  const providersPresent = computed(() => PROVIDER_IDS.filter(id => providerCounts.value[id]))
  const showProviders = computed(() => providersPresent.value.length > 1)
  const providerFacet = computed<ProviderFacet[]>(() =>
    showProviders.value
      ? providersPresent.value.map(id => ({
          id,
          ...ALL_PROVIDERS[id],
          n: providerCounts.value[id] ?? 0,
          color: PROVIDER_COLOR[id],
        }))
      : [],
  )

  // Tag facet: the capability tags present across this kind's models, with counts.
  const tagCounts = computed(() => {
    const counts = new Map<string, number>()
    for (const m of visibleModels.value) for (const t of m.tags) counts.set(t, (counts.get(t) ?? 0) + 1)
    return counts
  })
  const tagsPresent = computed<TagFacet[]>(() =>
    Object.keys(TAG_LABELS)
      .filter(slug => tagCounts.value.has(slug))
      .map(slug => ({ slug, label: tagLabel(slug), n: tagCounts.value.get(slug) ?? 0, color: tagColor(slug) })),
  )

  const selProviders = computed(() => filters[props.kind].providers)
  const selTags = computed(() => filters[props.kind].tags)
  // Something other than search/show-hidden is narrowing the list
  const anyFilter = computed(() => hasActive(props.kind) || uncensoredOnly.value)
  const hasFacets = computed(
    () =>
      providerFacet.value.length > 0 ||
      tagsPresent.value.length > 0 ||
      uncensoredCount.value > 0 ||
      hiddenCount.value > 0,
  )
  const filterCount = computed(() => selProviders.value.length + selTags.value.length + (uncensoredOnly.value ? 1 : 0))
  const activeChips = computed<ActiveChip[]>(() => [
    ...selProviders.value.map(id => ({
      key: `p-${id}`,
      label: ALL_PROVIDERS[id].label,
      color: PROVIDER_COLOR[id],
      off: () => {
        toggleProvider(props.kind, id)
      },
    })),
    ...selTags.value.map(slug => ({
      key: `t-${slug}`,
      label: tagLabel(slug),
      color: tagColor(slug),
      off: () => {
        toggleTag(props.kind, slug)
      },
    })),
    ...(uncensoredOnly.value
      ? [
          {
            key: 'unc',
            label: 'Uncensored',
            off: () => {
              uncensoredOnly.value = false
            },
          },
        ]
      : []),
  ])

  // Facets AND together (provider ∧ tag); within the tag facet a model needs
  // only one of the selected tags.
  function passesFilters(m: Model): boolean {
    if (m.id === props.modelValue) return true
    if (selProviders.value.length && !selProviders.value.includes(providerOf(m.id))) return false
    if (selTags.value.length && !m.tags.some(t => selTags.value.includes(t))) return false
    return true
  }
  const searched = computed(() => {
    const faceted = visibleModels.value.filter(passesFilters)
    const q = query.value.trim().toLowerCase()
    return q ? faceted.filter(m => m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q)) : faceted
  })

  // Favourites keep the order they were starred in; models that have left
  // the catalogue are skipped rather than shown broken
  const favouriteModels = computed(() => {
    const byId = new Map(searched.value.map(m => [m.id, m]))
    return favourites[props.kind].flatMap(id => byId.get(id) ?? [])
  })
  const otherModels = computed(() => searched.value.filter(m => !isFavourite(props.kind, m.id)).slice(0, MAX_LISTED))
  const filtered = computed(() => [...favouriteModels.value, ...otherModels.value])
  const sections = computed<ModelSection[]>(() => {
    const out: ModelSection[] = []
    if (favouriteModels.value.length) out.push({ id: 'fav', label: '★ Favourites', models: favouriteModels.value })
    // Only label the main list when there's a favourites list to tell it apart from
    out.push({ id: 'all', label: favouriteModels.value.length ? 'All models' : '', models: otherModels.value })
    return out
  })

  function clearAll(): void {
    clearFilters(props.kind)
    uncensoredOnly.value = false
  }

  return {
    showHidden,
    uncensoredOnly,
    visibleModels,
    hiddenCount,
    uncensoredCount,
    showProviders,
    providerFacet,
    tagsPresent,
    selProviders,
    selTags,
    anyFilter,
    hasFacets,
    filterCount,
    activeChips,
    filtered,
    sections,
    isFavourite,
    toggleFavourite,
    toggleProvider,
    toggleTag,
    clearAll,
  }
}
