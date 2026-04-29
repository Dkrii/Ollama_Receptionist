import { createDevKioskApp } from './modules/app.js';

const app = createDevKioskApp();

app.start();

window.devRegisterFaceProfile = app.registerFaceProfile;
