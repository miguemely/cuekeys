# Security

Please report security problems privately, using GitHub's **Report a vulnerability** button on the
repository's Security tab (private vulnerability reporting), rather than in a public issue.

Worth knowing when you assess a report:

- The host app opens outbound connections only: OSC (UDP), grandMA2 Telnet, and Companion HTTP and
  Satellite (TCP). It doesn't listen on any network port.
- grandMA2 Telnet credentials live in the layout file on the host. They're never written to the
  keypad (`config.firmware_view`), and Telnet itself isn't encrypted.
- The keypad acts as a USB keyboard. Anyone who can edit its `config.json` can make it type
  keystrokes.
