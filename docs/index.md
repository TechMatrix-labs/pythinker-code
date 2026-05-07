---
layout: home
hero:
  name: Pythinker Code
  text: ' '
  actions:
    - theme: brand
      text: English
      link: /en/
---

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vitepress'

onMounted(() => {
  const router = useRouter()
  router.go('/en/')
})
</script>
