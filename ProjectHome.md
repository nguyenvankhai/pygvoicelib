This library is a extremely light weight library that provides basic access to Google Voice API.

The library uses ClientLogin mechanism and supports Captcha locks on the account as well as session saving.

There are a few libraries out there to provide such API, however, the current python libraries fail to use the proper login, i.e. ClientLogin, and also non of them provide support for captcha.

In TELTUB, we started by using a few libraries out there, but we ended up writing one (this library) from scratch to fix the main issues we had: Captcha handling + Session saving