import { render } from 'preact';
import './ds/base.css';
import { App } from './app';
import { boot } from './lib/store';
import { connect } from './lib/sse';
import { onLink } from './lib/router';

document.addEventListener('click', onLink);
boot();
connect();
render(<App />, document.getElementById('app')!);
