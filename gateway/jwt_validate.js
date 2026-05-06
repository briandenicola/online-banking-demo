// JWT validation module for nginx njs
// Validates HS256 JWT tokens on protected API routes

function jwt_validate(r) {
    var auth = r.headersIn['Authorization'];
    if (!auth || !auth.startsWith('Bearer ')) {
        r.return(401, JSON.stringify({ error: 'Missing or invalid Authorization header' }));
        return;
    }

    var token = auth.substring(7);
    var parts = token.split('.');
    if (parts.length !== 3) {
        r.return(401, JSON.stringify({ error: 'Malformed JWT token' }));
        return;
    }

    try {
        var header = JSON.parse(Buffer.from(parts[0], 'base64url').toString());
        var payload = JSON.parse(Buffer.from(parts[1], 'base64url').toString());
    } catch (e) {
        r.return(401, JSON.stringify({ error: 'Invalid JWT encoding' }));
        return;
    }

    if (header.alg !== 'HS256') {
        r.return(401, JSON.stringify({ error: 'Unsupported algorithm' }));
        return;
    }

    var now = Math.floor(Date.now() / 1000);
    if (payload.exp && payload.exp < now) {
        r.return(401, JSON.stringify({ error: 'Token expired' }));
        return;
    }

    var expected_issuer = process.env.JWT_ISSUER || 'user-service';
    if (payload.iss && payload.iss !== expected_issuer) {
        r.return(401, JSON.stringify({ error: 'Invalid token issuer' }));
        return;
    }

    var secret = process.env.JWT_KEY;
    if (!secret) {
        r.return(500, JSON.stringify({ error: 'JWT secret not configured' }));
        return;
    }

    var signing_input = parts[0] + '.' + parts[1];
    var signature = require('crypto').createHmac('sha256', secret)
        .update(signing_input)
        .digest('base64url');

    if (signature !== parts[2]) {
        r.return(401, JSON.stringify({ error: 'Invalid token signature' }));
        return;
    }

    r.headersOut['X-User-Id'] = payload.sub || payload.nameid || '';
    r.internalRedirect('@upstream');
}

export default { jwt_validate };
