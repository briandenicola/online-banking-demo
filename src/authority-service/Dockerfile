FROM mcr.microsoft.com/dotnet/sdk:10.0-alpine AS build
WORKDIR /src

# Copy central package management
COPY Directory.Packages.props ./

# Copy shared projects
COPY src/shared/Contracts/*.csproj ./shared/Contracts/
COPY src/shared/Observability/*.csproj ./shared/Observability/

# Copy authority-service project
COPY src/authority-service/*.csproj ./authority-service/
RUN dotnet restore "./authority-service/authority-service.csproj"

# Copy everything else
COPY src/shared/Contracts/. ./shared/Contracts/
COPY src/shared/Observability/. ./shared/Observability/
COPY src/authority-service/. ./authority-service/

WORKDIR /src/authority-service
RUN dotnet publish -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:10.0-alpine AS runtime
WORKDIR /app
COPY --from=build /app/publish .

# The default policy is baked in so the image is never policy-less; a deployment overrides it
# by mounting its own file and pointing POLICY_FILE_PATH at it. Either way the service fails
# closed at startup if the file is missing or invalid — a bad mount is a crash loop, not a
# silently permissive ladder.
COPY config/authority-policy.yaml /app/config/authority-policy.yaml
ENV POLICY_FILE_PATH=/app/config/authority-policy.yaml

# user-service's RATIFIED role hierarchy, baked in read-only. This service consumes the ladder
# and never restates it: the policy file names signer roles, the hierarchy says what they are
# worth, and the loader refuses to start if they disagree. Two independent copies is how a
# customer's `user` claim came to satisfy a banker signature slot.
COPY src/user-service/config/role-hierarchy.yaml /app/config/role-hierarchy.yaml
ENV ROLE_HIERARCHY_PATH=/app/config/role-hierarchy.yaml

USER $APP_UID
ENTRYPOINT ["dotnet", "authority-service.dll"]
