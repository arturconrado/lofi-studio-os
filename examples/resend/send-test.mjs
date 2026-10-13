import { Resend } from 'resend';

// Replace re_xxxxxxxxx with your real API key in .env, never in this file.
const apiKey = process.env.RESEND_API_KEY?.trim();
if (!apiKey || apiKey === 're_xxxxxxxxx' || !apiKey.startsWith('re_')) {
  throw new Error('Set RESEND_API_KEY to your real Resend API key in .env.');
}

const resend = new Resend(apiKey);
const { data, error } = await resend.emails.send({
  from: 'onboarding@resend.dev',
  to: 'conraderp@gmail.com',
  subject: 'Hello World',
  html: '<p>Congrats on sending your <strong>first email</strong>!</p>',
});

if (error) {
  // Avoid printing provider responses that could contain sensitive information.
  console.error('Email was not accepted by Resend. Check your key and sender permissions.');
  process.exitCode = 1;
} else if (!data?.id) {
  console.error('Resend returned no email identifier. Check the delivery logs.');
  process.exitCode = 1;
} else {
  console.log('Email accepted by Resend:', data.id);
}
