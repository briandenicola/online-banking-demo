FROM mcr.microsoft.com/dotnet/sdk:9.0-alpine AS build
WORKDIR /src

# Copy shared Contracts project
COPY src/shared/Contracts/*.csproj ./shared/Contracts/
RUN dotnet restore "./shared/Contracts/Contracts.csproj"

# Copy account-service project
COPY src/account-service/*.csproj ./account-service/
RUN dotnet restore "./account-service/account-service.csproj"

# Copy everything else
COPY src/shared/Contracts/. ./shared/Contracts/
COPY src/account-service/. ./account-service/

WORKDIR /src/account-service
RUN dotnet publish -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:9.0-alpine AS runtime
WORKDIR /app
COPY --from=build /app/publish .
ENTRYPOINT ["dotnet", "account-service.dll"]