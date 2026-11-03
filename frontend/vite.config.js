import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import {Agent} from 'node:http'
export default defineConfig({plugins:[react()],server:{proxy:{'/api':{target:'http://127.0.0.1:8000',agent:new Agent({keepAlive:true,maxSockets:16})}}}})
