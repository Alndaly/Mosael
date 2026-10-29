"""支付渠道(ADR 0088 第 3 步:国内二维码预付)。

一个接口三件事(`base.PaymentChannel`):下单拿二维码、校验回调、主动查单。实现:支付宝当面付(`alipay`)、
微信支付 Native(`wechat`)。哪个渠道配了商户凭据就开哪个(`registry.channels_from_config`);测试注入同一套实现、
只把网络换成假的,生产代码里没有「测试模式」。

这里只管「和渠道说话、认不认这笔钱」;订单怎么记、到账后发什么在 `domain/orders`。
"""
