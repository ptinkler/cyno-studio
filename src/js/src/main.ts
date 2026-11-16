import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import './style.css'
import './composables/useTextSize' // sets the text size before anything is drawn

const app = createApp(App)
app.use(router)
app.mount('#app')
