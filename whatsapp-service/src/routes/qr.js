const express = require('express');
const qrcode = require('qrcode');
const state = require('../state');

const router = express.Router();

router.get('/qr', async (req, res) => {
    if (state.isConnected) {
        return res.send('<h2>WhatsApp is already connected. Session active.</h2>');
    }
    if (!state.qrCodeData) {
        return res.send('<h2>Waiting for QR code generation. Please refresh in a few seconds...</h2>');
    }
    try {
        const url = await qrcode.toDataURL(state.qrCodeData);
        res.send(`
            <html>
                <head><title>Link WhatsApp</title></head>
                <body style="display:flex;flex-direction:column;align-items:center;margin-top:50px;font-family:sans-serif;">
                    <h2>Scan this QR code with your WhatsApp App</h2>
                    <p>Go to WhatsApp -> Linked Devices -> Link a Device</p>
                    <img src="${url}" style="width:300px;height:300px;border:1px solid #ccc;padding:10px;" />
                    <script>
                        setInterval(() => window.location.reload(), 10000);
                    </script>
                </body>
            </html>
        `);
    } catch (err) {
        res.status(500).send('Error generating QR code image');
    }
});

module.exports = router;
