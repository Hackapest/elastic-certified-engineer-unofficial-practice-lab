"""Help-center articles and paraphrased questions for the semantic search templates.
Each question is worded differently from its article, so plain keyword search does poorly."""

ARTICLES = [
    ("reset-password", "Resetting a forgotten password",
     "If you can't sign in, use the 'Forgot password' link on the login page. We email you a link "
     "that lets you choose a new password; it expires after one hour."),
    ("shipping-times", "Delivery times for international orders",
     "Parcels to other countries usually arrive within 7 to 14 business days, depending on customs "
     "clearance in the destination country."),
    ("refunds", "Getting your money back",
     "Returned items are refunded to the original payment method within five days after the "
     "warehouse has inspected them."),
    ("two-factor", "Protecting your account with a second sign-in step",
     "Turn on two-step verification in your security settings: after your password, you confirm "
     "each sign-in with a code from an authenticator app."),
    ("gift-cards", "Paying with vouchers",
     "Vouchers can be combined with other payment methods at checkout. Unused balances stay on the "
     "voucher for three years."),
    ("size-guide", "Finding clothes that fit",
     "Our measurement charts compare chest, waist and inseam across brands, so you can choose the "
     "right size before you order."),
    ("cancel-order", "Stopping an order before it ships",
     "Orders can be withdrawn from your order history as long as they haven't left the warehouse. "
     "After that, send the parcel back instead."),
    ("newsletter", "Managing marketing emails",
     "Unsubscribe from promotional messages with the link at the bottom of every email, or in your "
     "communication preferences."),
]

QUESTIONS = [
    ("I don't remember how to log in to my account", "reset-password"),
    ("How long until my package reaches Canada?", "shipping-times"),
    ("When will I be reimbursed for the jacket I sent back?", "refunds"),
    ("Can I add an extra security code when signing in?", "two-factor"),
    ("Is it possible to use a present card together with my credit card?", "gift-cards"),
    ("Which trouser size should I pick?", "size-guide"),
    ("I changed my mind, can I undo my purchase before delivery?", "cancel-order"),
    ("Stop sending me promotions", "newsletter"),
]
