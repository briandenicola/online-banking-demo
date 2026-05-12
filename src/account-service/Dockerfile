FROM mcr.microsoft.com/dotnet/sdk:9.0-alpine AS build
WORKDIR /src

# Copy central package management
COPY Directory.Packages.props ./

# Copy shared projects
COPY src/shared/Contracts/*.csproj ./shared/Contracts/
COPY src/shared/Observability/*.csproj ./shared/Observability/

# Copy service project and restore
COPY src/account-service/*.csproj ./account-service/
RUN dotnet restore "./account-service/account-service.csproj"

# Copy everything else
COPY src/shared/Contracts/. ./shared/Contracts/
COPY src/shared/Observability/. ./shared/Observability/
COPY src/account-service/. ./account-service/

WORKDIR /src/account-service
RUN dotnet publish -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:10.0-alpine AS runtime
WORKDIR /app
COPY --from=build /app/publish .
USER $APP_UID
ENTRYPOINT ["dotnet", "account-service.dll"]